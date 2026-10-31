---
title: fund_performance_review
app_file: app.py
sdk: gradio
sdk_version: 6.30.0
---

# Fund Performance Review

A web app that drafts an **investment oversight review** of a fund as a two-page Executive Report and a Detailed Report: is the fund doing what it
promised, how did it do against its index, did investors get a fair outcome, and is its fee justified? It gives
a **suggested verdict** (Satisfied / Monitor / Action needed) and a suggested conclusion, with an evidence
dashboard; the analyst makes the judgement and signs.

**Code does the maths and the ratings, AI reads and writes, and a person makes the call.**

> **Data sharing:** This API key has OpenAI data sharing on: public data only, never upload confidential or client data.

The build specification is [`docs/FUND_PERFORMANCE_AGENT_SPEC.md`](docs/FUND_PERFORMANCE_AGENT_SPEC.md).

## How it works

```
Upload: price file (CSV/Excel) + factsheet (PDF/Word) [+ KID, peer factsheets] + a question   or, Advanced: JSON files
   │
   ├─ Task Planner (AI)       turns the question into tasks from a fixed menu; code keeps all four ratings
   ├─ Extractor Agent (AI)    reads the documents; code finds every value in them and flags any it cannot
   ├─ Approved peers          config/peers.yaml per benchmark, used when you give no peer (factsheets in data/peers/)
   ├─ Data checks (code)      dates, gaps, repeated prices, currency, pre-launch prices
   ├─ Mandate Agent (AI)      reads the objective; the profile wins on any disagreement
   ├─ Calculator (code)       returns, risk, tracking difference and error, factsheet precedence
   ├─ Peer checks (code)      currency, pricing time, share class, income vs accumulation; peers averaged
   ├─ Scorecard (code)        4 ratings and the suggested verdict, from config/thresholds.yaml
   ├─ Evidence (code)         yearly gaps, hit rate, t-test, peer percentile; conclusion, points, questions
   ├─ Research (AI + code)    Search Agent: approved pages + up to 5 web searches planned by the Task Planner,
   │                          running alongside the calculator; code vets dates, relevance and figures
   ├─ Findings and actions    written by code
   ├─ Reporting Agent (AI)    the summary and a cited market context ([n], no figures), one draft
   ├─ Judge (AI) + code       code checks every figure and citation; the Judge checks facts, reasoning, prompt
   │                          injection and clarity; one targeted rewrite at most; code's own conclusion is the fallback
   └─ Reports (code)          report_executive.pdf (2 pages as a target, more rather than cut) and report.pdf
                              (Detailed: the executive pages plus Appendices A–D); optional email (off by default)
```

Every run is saved in `runs/<timestamp>/`: `report.pdf` (Detailed), `report_executive.pdf`, `facts.json`, `run_log.txt` and `log.json` (each step,
its inputs and its outputs).

## Run it on your computer

```bash
pip install -r requirements.txt
cp .env.example .env            # add your OPENAI_API_KEY
python app.py                   # opens on http://127.0.0.1:7860
```

Pick a case under **Choose a test case** and click **Run Fund Review**: **Synthetic Demo** (made-up data, in the
repository), **Fidelity Index US P Acc GBP**, **Vanguard FTSE Global All Cap Index Fund GBP Acc** or **Upload Your Own
Fund**. A real-fund case runs the full Live AI workflow where AI runs are on (else its prevalidated Quick inputs, no
AI). The real cases' files are private (`data/demos/`, or the folder in `FUND_DEMO_DATA`; see
`docs/TEST_CASES.md`): a case whose files are missing is still listed, says which files are missing, and is never
replaced by made-up data. With
`APP_USERNAME` and `APP_PASSWORD` set in `.env`, the page asks for them before it opens; on your own computer you
can leave them blank (no login).

AI is off unless `AI_RUNS_ENABLED=true` (in `.env` locally; on a server the login must be set as well). Without
the private demo files (as on Render), the demo is a made-up fund.

For a real fund: add the price file and the factsheet (KID and peer factsheets optional; for an S&P 500 fund the
approved peers are used) and click **Run Fund Review**; code checks every value the agent read. The KID, peer
factsheets and JSON inputs are under **Additional options**. When the review finishes, the page shows a dashboard (assessment, evidence quality, headline figures, items
needing attention, the four ratings, details) and the PDF to download; choose **Management** for a short view or
**Investment Analyst** for the full detail. There is no Offline switch on the page: the demo runs
without AI, and for development `FUND_REVIEW_OFFLINE=1 python app.py` runs every review without AI.
Put the approved peers' factsheets in `data/peers/` (gitignored; found by the ISIN).

From the command line:

```bash
PYTHONPATH=src python -m fund_performance.run_report --data data/test1            # with AI
PYTHONPATH=src python -m fund_performance.run_report --data data/test1 --offline  # no AI calls
PYTHONPATH=src python -m fund_performance.run_report --data data/test1 --from-documents  # read the PDFs with AI
```

Tests: `pytest -q` (AI calls are mocked; `pytest --run-live` runs the few live tests).

## Deploy on Render

1. In the Render dashboard: **New > Blueprint**, pick this repository. `render.yaml` sets up the web service
   (`python app.py`, free plan, deploys from `main`).
2. Enter the secrets when Render asks: `OPENAI_API_KEY`, `APP_USERNAME` and `APP_PASSWORD`. The page asks for the
   username and password before it opens. Without them set, AI runs are off and only the offline demo works, so a
   public link cannot spend your API credit. Daily and one-at-a-time limits on AI runs are in
   `config/settings.yaml`. `RESEND_API_KEY`, `EMAIL_FROM` and `EMAIL_TO` (the recipients) are only needed to
   email the report.
3. After a push to `main`, Render rebuilds and redeploys.

Runs are kept on the server's disk until the next deploy (Render's free plan has no permanent disk).

## Settings

| File | What it holds |
|---|---|
| `config/thresholds.yaml` | Rating thresholds and run limits (illustrative, to be agreed with the oversight team) |
| `config/models.yaml` | The model for each AI agent |
| `config/sources.yaml` | Approved web pages per fund and market, fetched by code |
| `config/settings.yaml` | Timeouts per AI step, limits on AI runs, the significance test level, and email on/off (off by default; recipients come from `EMAIL_TO`) |
| `config/peers.yaml` | Approved peer funds per benchmark (factsheets in `data/peers/`), optional sector average OCF |

Everything in `data/` is gitignored: the repository is public, so price files, factsheets and KIDs stay local.
