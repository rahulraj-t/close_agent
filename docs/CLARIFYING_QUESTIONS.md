# Clarifying questions (max 3 allowed; ranked by how much the answer changes the design)

**Q1. FX basis.** Are the EUR and GBP rows in `trial_balance.csv` in local currency or already translated to USD? Untranslated the TB is off by -4,800; translated at the supplied rates it is off by ~+182k, and GBP has no period-end rate. Which reading is correct, and if local, what rate and policy (closing for BS, average for P&L, historical for equity) should apply to GBP?

**Q2. Period and equity roll.** Are P&L balances quarter-to-date or year-to-date, and is the TB pre- or post-closing? The prior TB has no P&L accounts and does not balance (2,832,800 Dr), and retained earnings rises 2.06M between periods with P&L still open. What explains the RE movement (dividends, close of prior year, restatement), so the SOCIE can be walked?

**Q3. Intercompany and entity scope.** Is this one legal entity or a consolidation input? JE-008 debits and credits 2170 for the same amount; should an IC settlement hit cash, and are IC balances eliminated against a counterparty TB we will receive? (Also: who owns approval of new COA nodes such as 6315?)

