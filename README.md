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

Choose a question type and edit the question. Use **+ Add** to upload multiple public documents or choose a test
case. The attachment table shows detected roles; confirm ambiguous documents, correct roles, or delete a row before
running. A fund price history and main factsheet are required for a live review; a KID and peer factsheets are
optional. Separate benchmark series may be uploaded as CSV/Excel with date and index-level columns; confirm the
benchmark name, currency and pricing time. The name, currency and pricing time must match the fund profile. Dates must
match the fund price dates exactly, and a separate series cannot replace an
index already present in the fund price file. Benchmark PDF/Word documents may be attached as evidence with a
publication/as-at date for each document; they are checked for date, relevance and conflicting return figures, treated
as untrusted source material, and do not supply calculation inputs. The analyst supplies the document dates; confirm
them against the original documents. Documents whose date, relevance or return figures fail the existing source checks
are excluded. Benchmark documents must contain readable text of at most 12,000 characters each.

If a fund's numerical investment horizon is not established, the review uses the configured standard period for
comparisons and identifies it as an analysis period, not a documented holding recommendation. Missing ongoing
charges leave fee-dependent ratings and calculations unavailable. The current workflow still requires usable fund
prices; a document-only qualitative report is not yet available.

The Synthetic Demo uses prevalidated inputs and runs without AI. Fidelity and Vanguard appear even when their private
files are missing, and missing cases are never replaced by synthetic data. Real-fund cases and custom uploads require
Live AI. AI is off unless `AI_RUNS_ENABLED=true`; on a server a login is also required. With `APP_USERNAME` and
`APP_PASSWORD` set in `.env`, the page asks for them before it opens. `FUND_REVIEW_OFFLINE=1` remains a development
setting. The command-line JSON workflow remains available below.

The results show the answer, supporting evidence, next step, suggested verdict, ratings and both PDF downloads.
Data-quality warnings remain visible; detailed figures, sources and technical information can be expanded. Approved
peer factsheets can also be placed in `data/peers/` (gitignored; found by ISIN).

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
