# Architecture: agentic financial-statement generation

Scope: design for all four statements; prototype for **one slice** (intake gate + manual-adjustments agent + pre/post reconciliation). Numbers below come from running that prototype on the mock data (`output/`).

## 1. Decomposition: "generate financials" is seven problems with different reliability needs

| # | Sub-problem | Nature | Who does it | Tolerance for error |
|---|---|---|---|---|
| 1 | Parse/normalise TB, COA, FX, adjustments | Deterministic | Code | Zero |
| 2 | Map accounts to COA nodes (new/ambiguous/orphan) | Judgement + retrieval | **LLM proposes, rules gate, human approves** | Zero silent errors; low confidence is fine if escalated |
| 3 | Validate adjustments (balance, accounts, net-zero patterns, period) | Deterministic rules | Code | Zero |
| 4 | Judge adjustment *reasonableness* (does 11,200 tie to the rate table?) | Rules + analytics | Code computes, human decides | Flag, never silently change |
| 5 | FX translation / revaluation, IC elimination | Deterministic given policy | Code | Zero |
| 6 | Build BS / P&L / CF / SOCIE | Arithmetic over a mapped ledger | Code | Zero |
| 7 | Explain, reconcile, triage exceptions, draft questions to humans | Language + analysis | **LLM for wording; deterministic facts/decisions** | No unsupported claims intended; mechanical checks are partial safeguards |

## 2. Agent topology: one deterministic pipeline, two narrow agents, one human queue

I would **not** build a swarm and would **not** prompt a frontier model with the TB. The system is a deterministic pipeline of typed stages with persisted artifacts between them. LLM calls exist in exactly two places, plus a human queue.

```
 inputs ──► [1 Intake gate]──► [2 Mapper agent*]──► [3 Adjustment gate]──► [4 Ledger engine]──► [5 Statement builder]
 (code)       defects list      proposals+score       decisions per JE       FX, IC, post          BS/PL/CF/SOCIE
                                    │                      │                     │                      │
                                    └──────────┬───────────┴─────────────┬───────┘                      ▼
                                          Exception queue  ◄───  [6 Verifier (code)] ──fail──► repair loop (max 2) ──► human
                                          (human approves)                │ pass
                                                                          ▼
                                                              [7 Explainer agent*] + audit pack
```
`*` = LLM. Everything else is code. Why not a single agent with tools? Because the failure modes are different per stage (a wrong mapping is silent and compounding; a wrong sum is loud), and stage artifacts give us idempotency and replay. Why not many sub-agents? Stages 1, 3, 4, 5, 6 have no reasoning in them; making them agents adds latency, cost and non-determinism and removes nothing. Two LLM agents is the minimum that matches where judgement exists.

### Where the AI earns its keep (and where it must not)
- **Mapper agent**: ERP exports use codes the COA has never seen (here `9999 Suspense`, `6315`, a prior-period `6905` that became `6900`). It retrieves candidate nodes (name embeddings + code-range + parent-sibling features + historical mappings), proposes a node with a confidence and a one-line rationale, and **abstains** when no candidate clears the threshold or the account is inherently non-mappable (suspense/clearing).
- **Explainer agent**: turns machine findings into a finance-readable narrative (rejections, variance commentary, "why did equity move"), and drafts the clarifying question to send to the preparer.
- **Never the LLM**: any amount, any sum, any accept/reject decision, any statement line. The LLM may only reword deterministic findings. The prototype applies two narrow mechanical checks to optional LLM text: every numeric token must occur in the supplied facts, and the exact structured status label must remain present. These are **numeric/status consistency checks, not proof of factual grounding**; they cannot detect every false claim, omitted caveat, or misleading paraphrase. The deterministic decision in `adjustment_decisions.json` remains authoritative, and template text is used if either check fails.

## 3. Failure modes and how each is handled

| Failure mode | Control | Seen in mock data |
|---|---|---|
| **Hallucinated mapping** | Mapper output is a *proposal* with confidence. Auto-apply only if (a) confidence ≥ 0.95, (b) an exact historical mapping exists, **and** (c) type/normal-balance/statement are consistent with the target. Otherwise → human queue. Suspense/clearing names are never auto-mapped. Every approved mapping is stored (versioned) and becomes a deterministic lookup next run, so the LLM is asked once per new account. Offline test: replay history and measure precision of auto-applied mappings; the threshold is tuned for ~0 false auto-maps, not for coverage. | `9999` held in suspense, not mapped; `6905→6900` proposed at 0.91 → human |
| **Debits ≠ credits after adjustments** | Per-entry balance check in `Decimal` (JE-level); batch invariant: post-TB imbalance **must equal** pre-TB imbalance, else the run aborts. The agent never "fixes" an unbalanced entry; it quarantines and offers *options* (which side to change, or a missing third line). | JE-002 off by 3,500.00 → quarantined |
| **Account fits no COA node** | Orphan bucket (`UNMAPPED`) shown as its own line on the BS, never netted into another line, and **blocks "final" status**. | TB `9999` 12,400.00; JE-005 → `6315` |
| **FX gap** | Rate hierarchy: period-end → *flag* + average-rate fallback in sensitivity only → block. Translation policy is explicit per account class (BS at closing, P&L at average, equity at historical, difference to CTA 3310). Missing closing rate for a balance-sheet currency means that currency's BS lines are **provisional**. | GBP has no period-end rate; GBP cash 412,300 cannot be revalued or checked |
| **Same-account / net-zero entry** | Quarantine entries where each account nets to zero; label the observed pattern, not an inferred cause. A same-account net-zero pattern is suspicious but does not by itself prove circularity. For IC, require counterparty-leg evidence and cross-entity elimination checks at consolidation. | JE-008 debits and credits 2170 by 320,000 → quarantined as `SAME_ACCOUNT_NET_ZERO`; ask for business-event and counterparty evidence before proposing a correction |
| **Prior-period drift / restatement** | Mapping versioned by period; comparatives are produced from a *restated-to-current-COA* prior TB with an explicit bridge; any restatement is a separate, labelled column. | `6905`→`6900` rename; prior TB itself is out of balance by 2,832,800.00 |

### Defects found beyond those listed in the PDF (all in the prototype's `intake_findings.json`)
1. **FX amount basis is ambiguous and decisive.** Untranslated, the TB is off by only **-4,800.00**; translating EUR at 1.095 and GBP at the average rate makes it off by **+182,460.20**. The data are therefore most plausibly already in USD with a currency *tag*, which contradicts the README ("sum after translation"). Prototype default: treat as functional; surfaced as question Q1.
2. **Depreciation tie-out**: accumulated depreciation moved 850,000 since the prior period, exactly equal to booked expense, so JE-006's 215,000 "catch-up" sits on a complete quarter (+25.3%) and may duplicate.
3. **JE-003 does not tie** to any recomputation from the rate table (10,730.20 vs average; 19,809.60 vs opening; booked 11,200.00), and the GBP leg cannot be revalued at all.
4. **JE-005 would be a no-op if repaired the obvious way** (re-pointing `6315` to `6310`, the other leg) so the right fix is a COA change, not a re-map.
5. **Prior TB** is unbalanced by 2,832,800.00 and has no P&L accounts; **retained earnings** moves 5,180,000 → 7,240,000 (+2.06M) with P&L still open, so the SOCIE cannot walk without a dividend/restatement/close explanation.
6. **Duplicate `6310`** rows have *different* amounts (245,000 and 38,500), so it is not a re-export duplicate by amount; summed but flagged.
7. COA: `1150` and `2170` cash-flow category `TBD`; `3200/3300/3310` no cash-flow category; `8000` typed Expense but acts as a header with no parent; `1290` empty header; `7000` no normal balance; `7100/7300/7310/7400` types disagree with sign behaviour. Also `PPE cost 17,007,700` rises 5.2M in one quarter (odd to the nearest 100): worth an analytic flag.

## 4. Validation and self-correction loop (statement stage; prototype implements the adjustment-gate part)

Verifier checks (code, run before any output leaves the system), in order:
1. Every TB row is accounted for exactly once (mapped, orphaned, or excluded with reason). Sum of mapped + orphan = TB total.
2. Every posted JE balances; post-TB imbalance == pre-TB imbalance (**implemented, asserted**).
3. Assets = Liabilities + Equity + (current-period earnings not yet closed). Any residual is printed as `UNEXPLAINED DIFFERENCE`, never plugged.
4. P&L net income == change in the equity roll-forward; SOCIE closing == BS equity.
5. Cash-flow closing cash == BS cash (needs the TBD cash-flow categories resolved).
6. Comparatives: opening balances == prior period closing.
7. Sign/normal-balance sanity and analytic flags (e.g. depreciation tie-out, 100x outliers).

On failure: the verifier emits a *typed* failure (`code`, `accounts`, `amount`). A repair step may do only **deterministic, reversible** things (re-run with a different already-approved mapping version, exclude a quarantined JE). After at most two attempts, or for any failure that would need an assumption (FX basis, plug), the run stops with status `DRAFT/BLOCKED` and the exception queue explains what a human must decide. The system is allowed to say "I cannot produce a final statement"; it is not allowed to guess.

## 5. Traceability: any BS cell back to source rows

Every statement cell stores a **lineage record**, not just a number:
`cell → [statement line] → [COA node(s)] → [mapping id + version + approver] → [TB source rows: file hash, line no.] ∪ [JE id, line no., source doc, decision id] ∪ [FX rate row + policy]`.
Implementation: an append-only `ledger_lines` table (`run_id, account, amount, origin = TB|JE|FX|ELIM, origin_ref`); statements are `GROUP BY` views over it, so a cell is *by construction* the sum of its lineage rows and the auditor can drill down with a query, not an explanation. The prototype already does this at account level: `output/reconciliation.json` carries `tb_lines` (CSV line numbers) and `adjustments` (JE id, line, source) for every account. Runs are immutable and keyed by `hash(inputs + mapping_version + policy_version + code_version)`, so re-running gives the same answer (idempotency) and an auditor can reproduce any past run.

## 6. Human-in-the-loop and override
- Single exception queue with typed items (mapping, quarantined JE, FX gap, unexplained difference), each with evidence, options and the cost of leaving it unresolved.
- Human decisions are data (who/when/why), versioned, and replayed on the next run. Overrides never edit source rows; they add a layered adjustment.
- Materiality thresholds are configuration, not model judgement.

## 7. The slice I built and why
I chose the **manual-adjustments agent** plus the intake gate and pre/post reconciliation: it is where the PDF's seeded failure modes concentrate (imbalance, unknown account, circular IC, FX), it forces the deterministic/LLM boundary to be explicit, and the reconciliation gives the auditor-trace story a concrete implementation. Results on the mock batch:

| JE | Decision | Reason |
|---|---|---|
| 001, 004, 007, 009, 010 | Accepted | Balanced, valid accounts, in period |
| 003 FX reval | Accepted with flags | 11,200 does not tie to rate table; GBP has no closing rate |
| 006 Depreciation | Accepted with flags | Full quarter already booked |
| 002 | **Quarantined** | Dr 28,500 ≠ Cr 25,000 (3,500 gap) |
| 005 | **Quarantined** | Account 6315 not in COA |
| 008 | **Quarantined** | Same-account net-zero: debits and credits 2170 for 320,000; suspicious no-op pattern, not proof of circularity |

Effect: net income 6,006,500.00 → 4,794,700.00 after the posted entries; TB imbalance stays at -4,800.00 (adjustments are balanced; the pre-existing gap is neither hidden nor plugged).
Decisions: quarantine on any ERROR; accept-with-flags on WARN-only (included but visible) since blocking on an analytic flag would stall the close over immaterial items. This policy is configurable.

## 8. Assumptions (to be confirmed; see `CLARIFYING_QUESTIONS.md`)
A1 TB amounts are already functional currency (evidence in §3). A2 P&L balances are for the quarter (depreciation/amortisation tie to balance-sheet movements). A3 Single reporting entity (no consolidation in this data). A4 Debits positive in the signed model; all amounts `Decimal`.
