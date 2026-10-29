import os
from decimal import Decimal as D
import pytest
from closeagent import ingest as I, adjustments as A, recon as R, explain as E

IN = os.path.join(os.path.dirname(__file__), "..", "inputs")
p = lambda n: os.path.join(IN, n)


@pytest.fixture(scope="module")
def ctx():
    coa, fx = I.load_coa(p("chart_of_accounts.csv")), I.load_fx(p("fx_rates.csv"))
    rows = I.load_tb(p("trial_balance.csv"))
    bal, lin, names, f = I.normalise_tb(rows, coa, fx)
    pbal, *_ = I.normalise_tb(I.load_tb(p("prior_period_tb.csv")), coa, fx, "PRIOR")
    res = A.process(A.load_adjustments(p("manual_adjustments.json")), coa, bal, pbal, fx, rows)
    return dict(coa=coa, fx=fx, rows=rows, bal=bal, lin=lin, f=f, pbal=pbal, res=res, by={r["id"]: r for r in res})


def codes(r): return {x.code for x in r["findings"]}


def test_intake_finds_seeded_and_unseeded_defects(ctx):
    c = {x.code for x in ctx["f"]}
    assert {"DUPLICATE_ACCOUNT", "ORPHAN_ACCOUNT", "TB_UNBALANCED", "FX_AMOUNT_BASIS"} <= c
    assert ctx["bal"]["6310"] == D("283500.00")          # duplicate summed, flagged
    assert sum(ctx["bal"].values()) == D("-4800.00")      # reported, never plugged


def test_decisions(ctx):
    by = ctx["by"]
    assert by["JE-002"]["status"] == "QUARANTINED" and "UNBALANCED" in codes(by["JE-002"])
    assert by["JE-005"]["status"] == "QUARANTINED" and "UNKNOWN_ACCOUNT" in codes(by["JE-005"])
    assert by["JE-008"]["status"] == "QUARANTINED" and "SAME_ACCOUNT_NET_ZERO" in codes(by["JE-008"])
    assert by["JE-003"]["status"] == "ACCEPTED_WITH_FLAGS"
    assert by["JE-006"]["status"] == "ACCEPTED_WITH_FLAGS"
    for j in ("JE-001", "JE-004", "JE-007", "JE-009", "JE-010"):
        assert by[j]["status"] == "ACCEPTED"


def test_invariants_and_lineage(ctx):
    rows, post = R.reconcile(ctx["bal"], ctx["lin"], ctx["res"], ctx["coa"])
    assert sum(post.values()) == sum(ctx["bal"].values())
    r6310 = [r for r in rows if r["account"] == "6310"][0]
    assert [x["tb_line"] for x in r6310["tb_lines"]] == [48, 49]
    assert all(D(r["delta"]) == 0 for r in rows if r["account"] in ("6310", "6300", "2170"))  # quarantined => untouched


def test_unbalanced_never_posted(ctx):
    je = {"id": "X", "date": "2024-12-01", "description": "t", "lines": [{"account": "6100", "debit": 10, "credit": 0}, {"account": "2120", "debit": 0, "credit": 9}]}
    f, *_ = A.validate_entry(je, ctx["coa"], ctx["bal"], ctx["pbal"], ctx["fx"], ctx["rows"], set())
    assert any(x.code == "UNBALANCED" and x.severity == "ERROR" for x in f)


def test_out_of_period_and_header(ctx):
    je = {"id": "Y", "date": "2025-01-05", "description": "t", "lines": [{"account": "1100", "debit": 5, "credit": 0}, {"account": "2120", "debit": 0, "credit": 5}]}
    f, *_ = A.validate_entry(je, ctx["coa"], ctx["bal"], ctx["pbal"], ctx["fx"], ctx["rows"], set())
    assert {"OUT_OF_PERIOD", "HEADER_ACCOUNT"} <= {x.code for x in f}


def test_numeric_consistency_check_rejects_new_numbers_but_is_not_full_grounding():
    facts = "Debits 28,500.00 do not equal credits 25,000.00"
    assert E.numeric_consistent("Debits 28,500.00 vs 25,000.00", facts)
    assert not E.numeric_consistent("The gap is 4,200.00", facts)
    # The exact status label is a separate mechanical check; neither check proves truth.
    assert E.safe_rewrite("QUARANTINED: the gap is 28,500.00", facts, "QUARANTINED")
    assert not E.safe_rewrite("ACCEPTED: the gap is 28,500.00", facts, "QUARANTINED")
    assert not E.safe_rewrite("QUARANTINED: the gap is 4,200.00", facts, "QUARANTINED")


def test_net_zero_pattern_does_not_claim_circularity(ctx):
    finding = next(x for x in ctx["by"]["JE-008"]["findings"] if x.code == "SAME_ACCOUNT_NET_ZERO")
    assert "does not prove a circular intercompany transaction" in finding.message
    assert not any(x.code == "CIRCULAR_ENTRY" for x in ctx["by"]["JE-008"]["findings"])
