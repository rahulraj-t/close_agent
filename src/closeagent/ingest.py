"""Deterministic intake gate: load COA / TB / FX, normalise, and RECORD every defect.
Nothing is silently fixed. Every TB balance keeps the CSV row numbers it came from (lineage)."""
import csv
from collections import defaultdict
from difflib import SequenceMatcher
from .model import D, money, Finding


def load_coa(path):
    coa = {}
    for r in csv.DictReader(open(path, newline="")):
        coa[r["account_code"]] = r
    return coa


def audit_coa(coa):
    f = []
    kids = defaultdict(list)
    for c, r in coa.items():
        if r["parent_code"]:
            kids[r["parent_code"]].append(c)
    for c, r in coa.items():
        if r["cf_category"] == "TBD":
            f.append(Finding("COA_AMBIGUOUS_CF", "WARN", f"COA:{c}",
                f"{c} {r['account_name']} has cash-flow category 'TBD'; it cannot be placed on the cash-flow statement until a human assigns it."))
        if r["account_type"] == "Header" and not kids[c] and c != "1000":
            f.append(Finding("COA_EMPTY_HEADER", "INFO", f"COA:{c}", f"Header {c} {r['account_name']} has no child accounts."))
        if not r["parent_code"] and r["account_type"] != "Header":
            f.append(Finding("COA_ORPHAN_NODE", "WARN", f"COA:{c}",
                f"{c} {r['account_name']} is typed '{r['account_type']}' but has no parent and sits at the root; it is a header-like node ({c} has children {kids[c]})."))
        if r["account_type"] == "Header" and not r["normal_balance"]:
            f.append(Finding("COA_MISSING_NORMAL_BAL", "INFO", f"COA:{c}", f"Header {c} has no normal balance."))
        if r["statement"] == "BS" and r["account_type"] in ("Asset", "Liability", "Equity") and not r["cf_category"] and r["account_type"] != "Header":
            f.append(Finding("COA_NO_CF_CATEGORY", "WARN", f"COA:{c}",
                f"BS account {c} {r['account_name']} has no cash-flow category (needed to derive cash flow from balance movements)."))
        if r["account_type"] in ("Expense", "Revenue") and c in ("7300", "7310", "7400", "7100"):
            f.append(Finding("COA_TYPE_AMBIGUOUS", "INFO", f"COA:{c}",
                f"{c} {r['account_name']} is typed '{r['account_type']}' but can carry the opposite sign (gains vs losses); sign handling must use the balance, not the type."))
    return f


def load_fx(path):
    rates = {}
    for r in csv.DictReader(open(path, newline="")):
        rates[(r["currency"], r["rate_type"])] = D(r["rate"])
    return rates


def load_tb(path):
    rows = []
    for i, r in enumerate(csv.DictReader(open(path, newline="")), start=2):  # line 1 is header
        rows.append(dict(line=i, code=r["account_code"], name=r["account_name"], ccy=r["currency"],
                         debit=money(r["debit"]), credit=money(r["credit"])))
    return rows


def normalise_tb(rows, coa, fx, label="TB"):

    f = []
    bal, lin, names = defaultdict(lambda: D(0)), defaultdict(list), {}
    by_code = defaultdict(list)
    for r in rows:
        by_code[r["code"]].append(r)
        v = r["debit"] - r["credit"]
        bal[r["code"]] += v
        lin[r["code"]].append({"tb_line": r["line"], "ccy": r["ccy"], "signed": str(v)})
        names[r["code"]] = r["name"]
    for code, rs in by_code.items():
        if len(rs) > 1 and len({x["ccy"] for x in rs}) == 1:
            f.append(Finding("DUPLICATE_ACCOUNT", "WARN", f"{label}:{code}",
                f"Account {code} {rs[0]['name']} appears {len(rs)} times in the same currency (TB lines {[x['line'] for x in rs]}) "
                f"with different amounts ({', '.join(str(x['debit'] - x['credit']) for x in rs)}). They are summed ({bal[code]:,.2f}) "
                f"but a human should confirm these are two ledger lines and not a re-export of the same balance.",
                {"lines": [x["line"] for x in rs], "sum": str(bal[code])},
                ["Sum the lines (current behaviour)", f"Keep only the larger line {max(x['debit']-x['credit'] for x in rs):,.2f}", "Keep only the smaller line"]))
        if code not in coa:
            hint = _suggest(names[code], coa)
            f.append(Finding("ORPHAN_ACCOUNT", "ERROR", f"{label}:{code}",
                f"Account {code} '{names[code]}' (balance {bal[code]:,.2f} Dr) is not in the chart of accounts. "
                f"It is held in a suspense bucket and shown separately; it is never auto-mapped.",
                {"balance": str(bal[code]), "lines": [x["line"] for x in rs]}, hint))
        else:
            if coa[code]["account_name"].strip().lower() != names[code].strip().lower():
                f.append(Finding("NAME_MISMATCH", "INFO", f"{label}:{code}", f"TB name '{names[code]}' differs from COA name '{coa[code]['account_name']}'."))
            if coa[code]["account_type"] == "Header":
                f.append(Finding("POSTING_TO_HEADER", "ERROR", f"{label}:{code}", f"{code} is a header but carries a balance."))
    # multi-currency rows: evidence for assumption A1
    ccys = {r["ccy"] for r in rows}
    foreign = ccys - {"USD"}
    if foreign:
        d = sum(r["debit"] for r in rows); c = sum(r["credit"] for r in rows)
        f.append(Finding("FX_AMOUNT_BASIS", "WARN", f"{label}",
            f"Rows tagged {sorted(foreign)} could be in local currency or already in USD. Evidence: with NO translation the TB is off by {d - c:,.2f}; "
            f"with translation it is off by {_translated_diff(rows, fx)[0]:,.2f}. Treating amounts as already functional (USD) because that is the "
            f"reading under which the ledger is nearly balanced. Needs controller confirmation (question Q1).",
            {"untranslated_diff": str(d - c), "translated_diff": str(_translated_diff(rows, fx)[0]),
             "rate_fallbacks": _translated_diff(rows, fx)[1]}))
    tot = sum(bal.values())
    if tot != 0:
        f.append(Finding("TB_UNBALANCED", "ERROR", f"{label}",
            f"Trial balance does not balance: debits minus credits = {tot:,.2f}. The difference is reported, never plugged. "
            f"Statements built from this TB are DRAFT until it is explained.",
            {"diff": str(tot)}))
    return dict(bal), dict(lin), names, f


def _translated_diff(rows, fx):
    fallbacks, d, c = [], D(0), D(0)
    for r in rows:
        ccy = r["ccy"]
        if ccy == "USD":
            rate = D(1)
        elif (ccy, "period_end") in fx:
            rate = fx[(ccy, "period_end")]
        elif (ccy, "period_average") in fx:
            rate = fx[(ccy, "period_average")]
            if f"{ccy}: no period_end rate, used period_average {rate}" not in fallbacks:
                fallbacks.append(f"{ccy}: no period_end rate, used period_average {rate}")
        else:
            raise ValueError(f"no rate for {ccy}")
        d += r["debit"] * rate; c += r["credit"] * rate
    return (d - c).quantize(D("0.01")), fallbacks


def _suggest(name, coa, n=3):
    """Lexical candidates only, clearly labelled as suggestions. Real mapper (LLM + retrieval) is out of slice."""
    sc = sorted(((SequenceMatcher(None, name.lower(), r["account_name"].lower()).ratio(), c) for c, r in coa.items()
                 if r["account_type"] != "Header"), reverse=True)[:n]
    out = [f"Candidate {c} {coa[c]['account_name']} (lexical similarity {s:.2f})" for s, c in sc]
    out.append("Name 'Suspense' implies a clearing account: do NOT map to an operating account; ask the GL owner what it clears")
    return out


def compare_periods(cur_bal, prior_bal, coa, prior_names, cur_names):
    """Prior-period account-list drift (e.g. renamed / re-coded account)."""
    f = []
    gone = [c for c in prior_bal if c not in cur_bal]
    new = [c for c in cur_bal if c not in prior_bal]
    for c in gone:
        cand = []
        for n in new:
            if n not in coa:
                continue
            s = SequenceMatcher(None, prior_names[c].lower(), coa[n]["account_name"].lower()).ratio()
            same_block = c[:2] == n[:2]
            cand.append((round(s * 0.5 + (0.4 if same_block else 0) + (0.1 if abs(int(c) - int(n)) <= 10 else 0), 2), n))
        cand.sort(reverse=True)
        if cand and cand[0][0] >= 0.6:
            conf, n = cand[0]
            f.append(Finding("PRIOR_ACCOUNT_RENAMED", "WARN", f"PRIOR:{c}",
                f"Prior-period account {c} '{prior_names[c]}' ({prior_bal[c]:,.2f}) is absent now; likely renamed/re-coded to {n} "
                f"'{coa[n]['account_name']}' (confidence {conf:.2f}). Comparatives will not line up until a human confirms.",
                {"candidate": n, "confidence": conf}, [f"Map {c} -> {n} for comparatives", "Keep as separate line"]))
        else:
            f.append(Finding("PRIOR_ACCOUNT_GONE", "WARN", f"PRIOR:{c}", f"Prior-period account {c} has no current counterpart."))
    for n in new:
        if n in coa and all(x.subject != f"PRIOR:{n}" for x in f):
            pass
    return f
