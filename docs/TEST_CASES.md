# Test cases (Version 1)

The page offers four test cases under **Choose a test case**:

| Case | Data | Where its files live | Default run |
|---|---|---|---|
| Synthetic Demo | Made up (every figure invented) | `demo/sample_index_fund/` (in this repository) | Quick: no AI, seconds |
| Fidelity Index US P Acc GBP | Real S&P 500 tracker | private case folder `fidelity_us/` | Live AI workflow where AI runs are on, else Quick |
| Vanguard FTSE Global All Cap Index Fund GBP Acc | Real global equity tracker | private case folder `vanguard_global/` | Live AI workflow where AI runs are on, else Quick |
| Upload Your Own Fund | The analyst's own public documents | uploaded per review | Live AI workflow |

- **Picking a case.** It fills in the existing upload boxes and shows the fund, review date, loaded documents, return check, disclosures and sources. The review question stays editable.
- **The two real cases.** They run the same workflow as an upload: Extractor, Mandate and Task Planner (with its web searches), the Search Agent, the Reporting Agent and the Judge.
- **Never substituted.** A real case whose files are not installed stays listed. It names the missing files and fills in nothing; it is never replaced by synthetic data.

## Audit of the case files (31 Oct 2026)

| Case | Price data | Factsheet | KID | Peer | Benchmark evidence | Quick inputs (typed, checked) | Return check (prices vs factsheet, 0.05 pp) |
|---|---|---|---|---|---|---|---|
| Synthetic | ✓ | ✓ | (none; made up) | ✓ made-up peer | made-up index returns | ✓ | ✓ 1/3/5 years |
| Fidelity | ✓ monthly NAV CSV | ✓ Monthly factsheet (30 Sep 2026) | ✓ | ✓ HSBC American Index Acc C factsheet | Index returns and PNAV risk figures from the factsheet; **no index price series** | ✓ profile, factsheet, peer | ✓ 1/3/5 years |
| Vanguard | ✓ daily NAV Excel (later prices left out) | ✓ factsheet (30 Sep 2026) | ✓ KIID | ✓ HSBC FTSE All-World Index Fund Acc C (GB00BMJJJF91), monthly report **31 May 2026**: fee compared, returns not (different periods) | GBP benchmark returns from the factsheet; **no tracking error, beta or R² published and no GBP index price series** (missing evidence, disclosed) | ✓ profile, factsheet, peer | ✓ 1/3/5 years |

Missing evidence that cannot be completed without new sources:
- **Index price series.** There is none for the S&P 500 (NUK) or the FTSE Global All Cap in GBP, so tracking error, beta and R² are not calculated from prices. Fidelity uses the factsheet's figures. Vanguard shows them as missing evidence.
- **Vanguard peer at the review date.** The peer, HSBC FTSE All-World Index Fund Acc C, is verified from its official monthly report dated 31 May 2026.
  - That report confirms GBP, Acc C, accumulating, ISIN GB00BMJJJF91, OCF 0.130%, valuation at 12:00 UK and a GBP 1,000,000 minimum.
  - No official report dated 30 Sep 2026 could be obtained: the latest HSBC report a web search found is 31 Aug 2026, and HSBC's site is not reachable from the build session.
  - So code compares the peer's fee, but leaves its returns out of the value comparison, because they cover different periods.
  - Value for investors waits for a peer report dated 30 Sep 2026.
- **Benchmark difference.** The peer tracks the FTSE All-World Index (large and mid caps, about 4,200 stocks). The fund tracks the FTSE Global All Cap Index, which also includes small caps (about 10,200 stocks). The case discloses this; the peer is a close comparison, not an identical benchmark.

No figure was invented for any case. The manifests in `demo/library/` hold metadata only.

## Can the real case files be distributed?

**Not in this public repository.**
- The factsheets, KIDs and price downloads are published by Fidelity International, HSBC Asset Management, Vanguard and FTSE Russell under their own terms.
- Public availability is not a licence to republish them. `data/` stays gitignored, and the tests never print or commit their contents.

Until redistribution rights are confirmed, install the files **privately** on each machine or server that should offer the real cases.

## Installing the real cases on a server (Render)

A Render web service's own file system is reset on every deploy and restart. To keep the cases, use a **persistent disk**:

1. **Attach a disk.** In the Render dashboard, add a persistent disk to the service, for example mounted at `/var/data`. Disks need a paid instance type; check Render's current pricing. This is a production change, so make it only after approval.
2. **Point the app at the disk.** Set the environment variable `FUND_DEMO_DATA=/var/data/demos`.
3. **Upload the private case folders** with their structure intact:
   ```
   /var/data/demos/fidelity_us/quick/{Fidelity_Index_US_P_Acc.csv, fund_profile.json, factsheet_performance.json, peer.json}
   /var/data/demos/fidelity_us/documents/{Monthly_FactSheet.pdf, Key_Investor_Info.pdf, HSBC_American_Index_Fund_Acc_C.pdf}
   /var/data/demos/vanguard_global/quick/{Historical_Prices_Vanguard_FTSE_Global_All_Cap_GBP_Acc.xlsx, fund_profile.json, factsheet_performance.json, peer.json}
   /var/data/demos/vanguard_global/documents/{Vanguard_FTSE_Global_All_Cap_GBP_Acc_factsheet.pdf, Vanguard_FTSE_Global_All_Cap_GBP_Acc_KIID.pdf, HSBC_FTSE_All-World_Index_Fund_Acc_C_2026-05.pdf}
   ```
   Use the service's shell or SSH, for example `scp`.
4. **Check the installation.** Run `python scripts/check_test_cases.py /var/data/demos` on the server. Every case should say `ready`, with its return checks `ok`.
5. **Optional: approved peers.** To use approved peers on the Render server, put their factsheets on the same disk and set `FUND_PEER_FOLDER`, for example to `/var/data/peers`.

The Live AI runs also need `AI_RUNS_ENABLED=true`, the login (`APP_USERNAME`, `APP_PASSWORD`) and `OPENAI_API_KEY`, as before.

## Isolation

- Each review copies its inputs into its own temporary folder and writes its reports to its own run folder (`<time>-<random id>`).
- Run folders and Gradio's cached uploads older than `web.keep_runs_hours` (24) are deleted on a server.
- The case files themselves are only read, never changed.
- One AI review runs at a time (`web.max_ai_runs_at_once`).
