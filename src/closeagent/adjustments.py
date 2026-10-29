import json
from collections import defaultdict
from difflib import SequenceMatcher
from datetime import date
from .model import D, money, fmt, Finding

PERIOD_START, PERIOD_END = date(2024, 10, 1), date(2024, 12, 31)
TOL = D("0.01")


def load_adjustments(path):
    return json.load(open(path))


def _lines(je):
    out = []
    for i, l in enumerate(je.get("lines", [])):
        out.append(dict(idx=i, account=str(l.get("account", "")), debit=money(l.get("debit", 0)),
                        credit=money(l.get("credit", 0)), memo=l.get("memo", "")))
    return out


def validate_entry(je, coa, pre_bal, prior_bal, fx, tb_rows, seen_ids):
    f = []
    jid = je.get("id", "<missing id>")
    ls = _lines(je)

    def add(code, sev, msg, ev=None, opts=None):
        f.append(Finding(code, sev, jid, msg, ev or {}, opts or []))

    if jid in seen_ids:
        add("DUPLICATE_ID", "ERROR", f"Entry id {jid} was already used earlier in this batch.")
    if len(ls) < 2:
        add("TOO_FEW_LINES", "ERROR", "A journal entry needs at least two lines.")
    try:
        d = date.fromisoformat(je.get("date", ""))
        if not (PERIOD_START <= d <= PERIOD_END):
            add("OUT_OF_PERIOD", "ERROR", f"Date {d} is outside 2024-Q4.")
    except ValueError:
        add("BAD_DATE", "ERROR", f"Date '{je.get('date')}' is not a valid ISO date.")
    for l in ls:
        if l["debit"] < 0 or l["credit"] < 0:
            add("NEGATIVE_AMOUNT", "ERROR", f"Line {l['idx']+1} has a negative amount; use the opposite side instead.")
        if l["debit"] and l["credit"]:
            add("BOTH_SIDES", "ERROR", f"Line {l['idx']+1} has both a debit and a credit.")
    td, tc = sum(l["debit"] for l in ls), sum(l["credit"] for l in ls)
    if abs(td - tc) > TOL:
        diff = td - tc
        opts = [f"Credit side should total {fmt(td)} (raise a credit by {fmt(diff)})" if diff > 0 else f"Debit side should total {fmt(tc)} (raise a debit by {fmt(-diff)})",
                f"{'Debit' if diff > 0 else 'Credit'} side should total {fmt(tc if diff > 0 else td)} (reduce the larger side)",
                f"A third line of {fmt(abs(diff))} is missing; ask the preparer which account"]
        add("UNBALANCED", "ERROR", f"Debits {fmt(td)} do not equal credits {fmt(tc)}; the difference is {fmt(abs(diff))}.",
            {"debits": str(td), "credits": str(tc), "diff": str(diff)}, opts)
    for l in ls:
        a = l["account"]
        if a not in coa:
            cands = _candidates(a, l["memo"] + " " + je.get("description", ""), coa)
            add("UNKNOWN_ACCOUNT", "ERROR", f"Line {l['idx']+1} posts to account {a}, which is not in the chart of accounts.",
                {"account": a, "line": l["idx"] + 1}, cands + [f"Request a COA change to create {a} (needs owner approval)"])
        elif coa[a]["account_type"] == "Header":
            add("HEADER_ACCOUNT", "ERROR", f"Line {l['idx']+1} posts to {a} which is a header, not a postable account.")
    net = defaultdict(lambda: D(0))
    for l in ls:
        net[l["account"]] += l["debit"] - l["credit"]
    accts = {l["account"] for l in ls}
    if len(ls) >= 2 and all(abs(v) <= TOL for v in net.values()):
        # A net-zero pattern can indicate a no-op, but without counterparty/entity
        # evidence it does not establish a circular intercompany transaction.
        same_account = len(accts) == 1
        code = "SAME_ACCOUNT_NET_ZERO" if same_account else "NET_ZERO_ENTRY"
        account_text = ", ".join(sorted(accts))
        if same_account:
            msg = (f"All lines use account(s) {account_text}, and debits and credits net to zero for that account. "
                   "This is a same-account, net-zero entry that appears to have no accounting effect. "
                   "It is quarantined for review; this pattern alone does not prove a circular intercompany transaction.")
        else:
            msg = (f"Each account nets to zero within this entry ({account_text}), so the entry appears to have no net accounting effect. "
                   "It is quarantined for review; this pattern alone does not prove circularity.")
        add(code, "ERROR", msg,
            {"net": {k: str(v) for k, v in net.items()}, "account_count": len(accts)},
            ["Confirm the intended business event and whether the entry should have any accounting effect.",
             "If this is an intercompany settlement, obtain the counterparty/entity evidence and identify the actual settlement account before resubmitting."])
    # A one-sided IC warning applies only when the entry has not already been held
    # for a net-zero pattern. The absence of a counterparty leg is not proof of circularity.
    if any(a == "2170" for a in accts) and len(accts) == 1 and not any(x.code in {"SAME_ACCOUNT_NET_ZERO", "NET_ZERO_ENTRY"} for x in f):
        add("IC_ONE_SIDED", "WARN", "Intercompany entry touches only one intercompany account; the other entity's side cannot be verified from this entry alone.")

    # --- Reasonableness (WARN only: human judges) ---
    if not [x for x in f if x.severity == "ERROR"]:
        for a in accts:
            if a in coa and a in pre_bal:
                post = pre_bal[a] + net[a]
                if pre_bal[a] != 0 and (post > 0) != (pre_bal[a] > 0) and post != 0:
                    add("BALANCE_FLIP", "WARN", f"Account {a} {coa[a]['account_name']} flips from {fmt(pre_bal[a])} to {fmt(post)} (sign change) after this entry.")
        _fx_reval_check(je, ls, tb_rows, fx, add)
        _depr_tieout(ls, pre_bal, prior_bal, add)
    return f, ls, td, tc


def _candidates(acct, text, coa, n=3):
    """Sibling/lexical suggestions. Suggestions only; a human decides."""
    out = []
    near = [c for c in coa if coa[c]["account_type"] != "Header" and c[:2] == acct[:2]]
    sc = []
    for c in near:
        s = SequenceMatcher(None, text.lower(), coa[c]["account_name"].lower()).ratio()
        tok = sum(1 for w in coa[c]["account_name"].lower().replace("&", " ").split() if w in text.lower())
        sc.append((round(0.3 * s + 0.2 * tok + (0.3 if abs(int(c) - int(acct or 0)) <= 10 else 0), 2), c))
    for s, c in sorted(sc, reverse=True)[:n]:
        if s > 0.3:
            out.append(f"Use existing {c} {coa[c]['account_name']} (heuristic score {s:.2f}) - note: may make the entry a no-op if it is already the other leg")
    return out


def _fx_reval_check(je, ls, tb_rows, fx, add):
    if "fx reval" not in je.get("description", "").lower():
        return
    amt = sum(l["debit"] for l in ls)
    eur = sum(r["debit"] - r["credit"] for r in tb_rows if r["code"] == "1110" and r["ccy"] == "EUR")
    cands = {}
    if ("EUR", "period_end") in fx:
        for base in ("period_average", "opening"):
            if ("EUR", base) in fx:
                cands[f"EUR {fmt(eur)} x (period_end {fx[('EUR','period_end')]} - {base} {fx[('EUR',base)]})"] = money(eur * (fx[("EUR", "period_end")] - fx[("EUR", base)]))
    if any(abs(v - amt) <= D(1) for v in cands.values()):
        return
    gbp = sum(r["debit"] - r["credit"] for r in tb_rows if r["code"] == "1110" and r["ccy"] == "GBP")
    add("FX_REVAL_NOT_TIED", "WARN",
        f"Booked reval of {fmt(amt)} does not tie to any recomputation from the rate table: "
        + "; ".join(f"{k} = {fmt(v)}" for k, v in cands.items()) + ". "
        f"GBP cash ({fmt(gbp)}) has no period-end rate in fx_rates.csv so it cannot be revalued or checked at all. "
        f"Also confirm the TB's EUR balance was not already revalued, or this double counts.",
        {"booked": str(amt), "recomputed": {k: str(v) for k, v in cands.items()}},
        ["Accept as booked (immaterial, flagged)", "Replace with recomputed amount once the preparer confirms the base rate", "Obtain GBP period-end rate and revalue both currencies"])


def _depr_tieout(ls, pre_bal, prior_bal, add):
    accts = {l["account"] for l in ls}
    if "6500" in accts and "1211" in accts and "1211" in prior_bal:
        mv = -(pre_bal.get("1211", D(0)) - prior_bal["1211"])
        exp = pre_bal.get("6500", D(0))
        amt = sum(l["debit"] for l in ls if l["account"] == "6500")
        if mv == exp:
            add("DEPR_ALREADY_FULL", "WARN",
                f"Before this entry, accumulated depreciation already grew by {fmt(mv)} since the prior period, exactly equal to booked depreciation expense ({fmt(exp)}). "
                f"This {fmt(amt)} 'catch-up' therefore sits on top of a complete quarter ({amt/exp:.1%} extra). Confirm against the fixed-asset register that it is not a duplicate.",
                {"acc_dep_movement": str(mv), "expense": str(exp), "catch_up": str(amt)})


def process(batch, coa, pre_bal, prior_bal, fx, tb_rows):
    results, seen = [], set()
    for je in batch["entries"]:
        f, ls, td, tc = validate_entry(je, coa, pre_bal, prior_bal, fx, tb_rows, seen)
        seen.add(je.get("id"))
        errs = [x for x in f if x.severity == "ERROR"]
        warns = [x for x in f if x.severity == "WARN"]
        status = "QUARANTINED" if errs else ("ACCEPTED_WITH_FLAGS" if warns else "ACCEPTED")
        results.append(dict(id=je.get("id"), description=je.get("description"), source=je.get("source"), date=je.get("date"),
                            status=status, debits=str(td), credits=str(tc), lines=[{**l, "debit": str(l["debit"]), "credit": str(l["credit"])} for l in ls],
                            findings=f))
    return results
