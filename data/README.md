# data/

Fund files live here on your own computer only. Everything in this folder except this README is
gitignored, because the repository is public. Never commit price files, factsheets, KIDs or
answer keys.

```
data/
  test1/        Test 1: Fidelity Index US Fund P Acc (GB00BJS8SH10), as of 30 Sep 2026
    Fidelity_Index_US_P_Acc.csv     monthly NAV, Nov 2012 to Sep 2026
    Monthly_FactSheet.pdf           UK factsheet, 30 Sep 2026
    Key_Investor_Info.pdf           KID
    fund_profile.json               typed from the factsheet and KID
    factsheet_performance.json      typed from the factsheet (entered_by: manual)
  answer_key/   the manager's published Value Assessment Report. Never used as agent input;
                only for comparing results after a run.
```

Tests that need these files are skipped when the files are missing.
