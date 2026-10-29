# close-agent: adjustments agent + intake gate + reconciliation 
Take-home prototype for "agentic financial-statement generation". Start with `docs/ARCHITECTURE.md` (main artifact), then `docs/REFLECTION.md` and `docs/CLARIFYING_QUESTIONS.md`.

## Run
```
python3 -m pip install pytest            # only for tests; the prototype uses the stdlib
PYTHONPATH=src python3 -m closeagent.cli # reads ./inputs, writes ./output
PYTHONPATH=src python3 -m pytest -q
```


## What it does
1. **Intake gate** (`ingest.py`): loads COA, TB, prior TB, FX; records defects without fixing them (duplicate account, orphan account, unbalanced TB, FX basis ambiguity, prior-period rename, COA gaps).
2. **Adjustments agent** (`adjustments.py`, `explain.py`): deterministic rules decide ACCEPTED / ACCEPTED_WITH_FLAGS / QUARANTINED per journal entry; findings carry plain-English text and repair *options* (never auto-applied).
3. **Reconciliation** (`recon.py`): pre vs post TB, every delta line tied to JE id/line/source and TB CSV line numbers; invariants asserted.

JE-008 is classified as `SAME_ACCOUNT_NET_ZERO`: the pattern is quarantined as a suspicious no-op, but is not labelled proof of a circular intercompany transaction without counterparty/entity evidence.

## Output (`output/`)
`adjustment_explanations.md`, `adjustment_decisions.json`, `intake_findings.json`, `reconciliation.md`, `reconciliation.json`.

Inputs were used as provided (not sanitised). 
