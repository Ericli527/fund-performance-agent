# Stage 2.5: portable financial regression and CI

Run from the repository root with Python 3.13 and `requirements.txt` installed:

```sh
python -m pytest -m 'not live' -q -ra --junitxml=test-results.xml
python scripts/check_test_skips.py test-results.xml
```

The pull-request workflow runs these same commands without secrets. Live tests are **deselected**, not run.
JUnit results are retained even after failure. The audit fails on unexpected skips, failed/error tests or zero
executed tests. It matches both exact test identity and exact reason against the reviewed private-data allowlist;
missing the committed demo golden baseline is never an allowed skip. A failed pytest command still fails CI.
Do not add new entries merely to make CI green. Private cases may execute when their files are supplied locally.

## Private-data audit

The existing Test 1 assertions remain intact. Their portable counterparts are additive, not substitutes for
validating the actual Fidelity source documents. The baseline branch has 53 non-live private-data skipped cases
on a fresh checkout (including two private golden cases); six live tests are deselected. The handover's 57 count
includes test functions that also carry live markers. Exact identities/reasons are in `expected_private_skips.json`.

| Private-data area | Portable regression protection |
|---|---|
| `test_calc`: horizon returns, calendar/discrete years, risk, pre-launch exclusion | Synthetic monthly price file, independent arithmetic, full calculator path |
| `test_precedence`: official values, PNAV comparison, source/risk separation | File reader → checks → calculation → precedence → scorecard |
| `test_checks`, `test_io`: data checks and parsing | CSV/XLSX missing values, pre-launch prices, currency mismatch; existing synthetic date/gap/repetition tests |
| `test_scorecard`: Test 1 integrated ratings | Synthetic Green case, full offline Action needed and Pending data check runs |
| Test 1 controller, reporting, agent, model, peer and other integration cases | Existing mocked tests and demo golden remain; private-specific expectations still require private inputs |
| Private golden cases | Preserved unchanged; demo golden executes in CI |

See `fixtures/portable/README.md` for input provenance and independently derived expected values.
Existing synthetic tests continue to cover score boundaries, dual objectives, active funds, short history,
missing comparisons and repeated-price checks. This stage does not claim new complete end-to-end coverage of
all those scenarios or validation of the missing real Tests 2–4.

## Remaining limitation

The synthetic currency mismatch reaches Pending data check correctly. Its long warning used to push the old
PDF summary to six pages and stop the run; since Stage 3 both PDFs are built, the Executive Report keeps exactly two
pages and shows the warning in full, and the Detailed Report has it too (tested).
Financial calculations, thresholds, model configuration, agent workflows, UI, PDF code, and golden baselines
are unchanged. Human approval remains required. No live service or deployment is part of CI.

## Validation in the cloud environment

On 30 October 2026, Python 3.13.5: **520 passed, 53 expected private-data skips, 6 live tests deselected**
in a fresh source copy with no `data/test1/`, using the installed dependencies. Skip audit: **0 unexpected**.
All 18 new tests passed; the existing demo golden case passed without baseline changes. Workflow YAML parsed
successfully. GitHub-hosted execution remains unverified until the workflow is pushed and run on a pull request.
