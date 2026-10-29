from collections import defaultdict
from .model import D, fmt


def reconcile(pre_bal, lineage, results, coa):
    delta = defaultdict(lambda: D(0))
    why = defaultdict(list)
    for r in results:
        if r["status"] == "QUARANTINED":
            continue
        for l in r["lines"]:
            v = D(l["debit"]) - D(l["credit"])
            delta[l["account"]] += v
            why[l["account"]].append({"je": r["id"], "line": l["idx"] + 1, "signed": str(v), "memo": l["memo"], "source": r["source"], "status": r["status"]})
    post = defaultdict(lambda: D(0), pre_bal)
    for a, v in delta.items():
        post[a] += v
    assert sum(delta.values()) == 0, "accepted entries must net to zero"
    assert sum(post.values()) == sum(pre_bal.values()), "adjustments must not change TB imbalance"
    rows = []
    for a in sorted(set(pre_bal) | set(delta)):
        rows.append(dict(account=a, name=(coa.get(a) or {}).get("account_name", "NOT IN COA"), pre=str(pre_bal.get(a, D(0))),
                         delta=str(delta.get(a, D(0))), post=str(post[a]), tb_lines=lineage.get(a, []), adjustments=why.get(a, [])))
    return rows, post


def net_income(bal, coa):
    """P&L accounts only; credit-normal profit shown positive. Unmapped accounts excluded and said so."""
    return -sum(v for a, v in bal.items() if a in coa and coa[a]["statement"] == "PL")


def headline(pre, post, coa, results):
    ni0, ni1 = net_income(pre, coa), net_income(post, coa)
    return dict(net_income_pre=str(ni0), net_income_post=str(ni1), net_income_change=str(ni1 - ni0),
                tb_imbalance_pre=str(sum(pre.values())), tb_imbalance_post=str(sum(post.values())),
                quarantined_ids=[r["id"] for r in results if r["status"] == "QUARANTINED"])
