# Manual adjustment decisions (plain English)

```
JE-001 - Accrue Q4 bonus pool: Posted. No problems found.
  Effect: moves 850,000.00 between accounts (debits = credits).
```


```
JE-002 - Reclassify marketing spend wrongly booked to T&E: NOT posted. It is held back until the problem below is fixed.
  - Debits 28,500.00 do not equal credits 25,000.00; the difference is 3,500.00.
      option: Credit side should total 28,500.00 (raise a credit by 3,500.00)
      option: Debit side should total 25,000.00 (reduce the larger side)
      option: A third line of 3,500.00 is missing; ask the preparer which account
```


```
JE-003 - FX revaluation of EUR cash balance to period-end rate: Posted, but please review the flag(s) below.
  - Booked reval of 11,200.00 does not tie to any recomputation from the rate table: EUR 825,400.00 x (period_end 1.095 - period_average 1.082) = 10,730.20; EUR 825,400.00 x (period_end 1.095 - opening 1.071) = 19,809.60. GBP cash (412,300.00) has no period-end rate in fx_rates.csv so it cannot be revalued or checked at all. Also confirm the TB's EUR balance was not already revalued, or this double counts.
      option: Accept as booked (immaterial, flagged)
      option: Replace with recomputed amount once the preparer confirms the base rate
      option: Obtain GBP period-end rate and revalue both currencies
  Effect: moves 11,200.00 between accounts (debits = credits).
```

```
JE-004 - Bad debt provision top-up: Posted. No problems found.
  Effect: moves 45,000.00 between accounts (debits = credits).
```


```
JE-005 - Reclass conference travel from old code: NOT posted. It is held back until the problem below is fixed.
  - Line 1 posts to account 6315, which is not in the chart of accounts.
      option: Use existing 6310 Travel and Entertainment (heuristic score 0.61) - note: may make the entry a no-op if it is already the other leg
      option: Request a COA change to create 6315 (needs owner approval)
```


```
JE-006 - Depreciation catch-up — Q4: Posted, but please review the flag(s) below.
  - Before this entry, accumulated depreciation already grew by 850,000.00 since the prior period, exactly equal to booked depreciation expense (850,000.00). This 215,000.00 'catch-up' therefore sits on top of a complete quarter (25.3% extra). Confirm against the fixed-asset register that it is not a duplicate.
  Effect: moves 215,000.00 between accounts (debits = credits).
```


```
JE-007 - Deferred tax true-up: Posted. No problems found.
  Effect: moves 38,000.00 between accounts (debits = credits).
```


```
JE-008 - Intercompany settlement — UK sub: NOT posted. It is held back until the problem below is fixed.
  - All lines use account(s) 2170, and debits and credits net to zero for that account. This is a same-account, net-zero entry that appears to have no accounting effect. It is quarantined for review; this pattern alone does not prove a circular intercompany transaction.
      option: Confirm the intended business event and whether the entry should have any accounting effect.
      option: If this is an intercompany settlement, obtain the counterparty/entity evidence and identify the actual settlement account before resubmitting.
```


```
JE-009 - Accrue legal fees for ongoing litigation: Posted. No problems found.
  Effect: moves 75,000.00 between accounts (debits = credits).
```


```
JE-010 - Reclass long-term debt current portion: Posted. No problems found.
  Effect: moves 200,000.00 between accounts (debits = credits).
```


