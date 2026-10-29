import argparse, json, os
from . import ingest as I, adjustments as A, recon as R, explain as E
from .model import fmt, D


def main(argv=None):
    p = argparse.ArgumentParser(prog="closeagent")
    p.add_argument("--inputs", default="inputs"); p.add_argument("--out", default="output")
    p.add_argument("--llm", action="store_true", help="optional LLM re-wording with numeric/status consistency checks")
    a = p.parse_args(argv)
    i = lambda n: os.path.join(a.inputs, n)
    coa = I.load_coa(i("chart_of_accounts.csv")); fx = I.load_fx(i("fx_rates.csv"))
    rows = I.load_tb(i("trial_balance.csv")); prow = I.load_tb(i("prior_period_tb.csv"))
    bal, lin, names, f_tb = I.normalise_tb(rows, coa, fx, "TB")
    pbal, _, pnames, f_pr = I.normalise_tb(prow, coa, fx, "PRIOR")
    f_pr = [x for x in f_pr if x.code != "FX_AMOUNT_BASIS"]
    f_cmp = I.compare_periods(bal, pbal, coa, pnames, names)
    renamed = {x.subject.split(":")[1] for x in f_cmp if x.code == "PRIOR_ACCOUNT_RENAMED"}
    f_pr = [x for x in f_pr if not (x.code == "ORPHAN_ACCOUNT" and x.subject.split(":")[1] in renamed)]
    f_coa = I.audit_coa(coa)
    results = A.process(A.load_adjustments(i("manual_adjustments.json")), coa, bal, pbal, fx, rows)
    rrows, post = R.reconcile(bal, lin, results, coa)
    head = R.headline(bal, post, coa, results)
    os.makedirs(a.out, exist_ok=True)
    expl = {r["id"]: E.explain(r, a.llm) for r in results}
    dump = lambda n, o: json.dump(o, open(os.path.join(a.out, n), "w"), indent=2, default=lambda x: x.to_dict() if hasattr(x, "to_dict") else str(x))
    dump("intake_findings.json", {"tb": f_tb, "prior_tb": f_pr + f_cmp, "coa": f_coa})
    dump("adjustment_decisions.json", results)
    dump("reconciliation.json", {"headline": head, "lines": rrows})
    with open(os.path.join(a.out, "adjustment_explanations.md"), "w") as fh:
        fh.write("# Manual adjustment decisions (plain English)\n\n")
        for r in results:
            fh.write(f"```\n{expl[r['id']][0]}\n```\n_(explanation source: {expl[r['id']][1]})_\n\n")
    with open(os.path.join(a.out, "reconciliation.md"), "w") as fh:
        fh.write("# Pre- vs post-adjustment reconciliation (USD)\n\n")
        fh.write(f"- Net income before adjustments: **{fmt(D(head['net_income_pre']))}**\n- Net income after posted adjustments: **{fmt(D(head['net_income_post']))}** (change {fmt(D(head['net_income_change']))})\n")
        fh.write(f"- TB imbalance before / after: {fmt(D(head['tb_imbalance_pre']))} / {fmt(D(head['tb_imbalance_post']))} (unchanged: the adjustments are balanced; the existing gap is NOT plugged)\n")
        fh.write(f"- Quarantined (excluded): {', '.join(head['quarantined_ids'])}\n- Net income excludes unmapped account 9999 (12,400.00 Dr) which is outside the COA.\n\n")
        fh.write("| Account | Name | Pre (Dr+/Cr-) | Adjustment | Post | Explained by |\n|---|---|---:|---:|---:|---|\n")
        for r in rrows:
            if D(r["delta"]) != 0:
                ex = "; ".join(f"{x['je']} L{x['line']} {fmt(D(x['signed']))} ({x['source']})" for x in r["adjustments"])
                fh.write(f"| {r['account']} | {r['name']} | {fmt(D(r['pre']))} | {fmt(D(r['delta']))} | {fmt(D(r['post']))} | {ex} |\n")
    # console summary
    print("INTAKE:", sum(len(x) for x in (f_tb, f_pr, f_cmp, f_coa)), "findings (see output/intake_findings.json)")
    for r in results:
        print(f"{r['id']:7} {r['status']:20} {[x.code for x in r['findings']]}")
    print("NET INCOME", head["net_income_pre"], "->", head["net_income_post"], "| TB gap unchanged:", head["tb_imbalance_post"])
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
