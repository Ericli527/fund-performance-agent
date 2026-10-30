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
  demos/        the real-fund demo library (Stage 4B); metadata is in demo/library/*.yaml
    fidelity_us/
      quick/      Fidelity_Index_US_P_Acc.csv, fund_profile.json, factsheet_performance.json, peer.json
                  (peer: HSBC American Index Fund Acc C, typed from its factsheet, with benchmark_name)
      documents/  Monthly_FactSheet.pdf, Key_Investor_Info.pdf, HSBC_American_Index_Fund_Acc_C.pdf
    vanguard_global/
      quick/      Historical_Prices_Vanguard_FTSE_Global_All_Cap_GBP_Acc.xlsx (the download as it is),
                  fund_profile.json, factsheet_performance.json (GBP figures from Vanguard's factsheet,
                  calendar years from the KIID; returns given as annualised)
      documents/  Vanguard_FTSE_Global_All_Cap_GBP_Acc_factsheet.pdf, ..._KIID.pdf
      context/    FTSE_Global_All_Cap_Index_factsheet_USD.pdf (USD: listed as a source, never compared)
    golden/       the demos' golden-facts baselines
```

A demo whose files are missing is shown as unavailable on the page (nothing breaks); set FUND_DEMO_DATA to use
another folder. Real-fund source documents and data are not published (not in the repository, not on Render).

Tests that need these files are skipped when the files are missing.
