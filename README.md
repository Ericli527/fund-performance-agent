---
title: fund_performance_review
app_file: app.py
sdk: gradio
sdk_version: 6.30.0
---

# Fund Performance Review

A web app that drafts an **investment oversight review** of a fund as a 4-page PDF: is the fund doing what it
promised, how did it do against its index, did investors get a fair outcome, and is its fee justified? It gives
a **draft verdict** (Retain / Monitor / Review) for a person to approve and sign.

**Code does the maths and the ratings, AI reads and writes, and a person makes the call.**

> **Data sharing:** This API key has OpenAI data sharing on: public data only, never upload confidential or client data.

The build specification is [`docs/FUND_PERFORMANCE_AGENT_SPEC.md`](docs/FUND_PERFORMANCE_AGENT_SPEC.md).

## How it works

```
Upload: fund_profile.json + price file (CSV/Excel) + factsheet_performance.json (or factsheet/KID PDFs) [+ peer.json]
   │
   ├─ Extractor Agent (AI)    only without factsheet_performance.json: copies figures from the PDFs ("please verify")
   ├─ Data checks (code)      dates, gaps, repeated prices, currency, pre-launch prices
   ├─ Mandate Agent (AI)      reads the objective; the profile wins on any disagreement
   ├─ Calculator (code)       returns, risk, tracking difference and error, factsheet precedence
   ├─ Scorecard (code)        4 ratings and the draft verdict, from config/thresholds.yaml
   ├─ Research                approved pages fetched by code + up to 3 web searches (AI), vetted by code
   ├─ Findings and actions    written by code
   ├─ Market context (AI)     checked by code, then by the Evaluator Agent (AI)
   └─ Report (code)           4-page PDF with charts, approval box and appendix; optional email (Resend)
```

Every run is saved in `runs/<timestamp>/`: `report.pdf`, `facts.json`, `run_log.txt` and `log.json` (each step,
its inputs and its outputs).

## Run it on your computer

```bash
pip install -r requirements.txt
cp .env.example .env            # add your OPENAI_API_KEY
python app.py                   # opens on http://127.0.0.1:7860
```

Click **Use the demo files (made-up fund)** and **Run the review** to try it without any AI calls.

From the command line:

```bash
PYTHONPATH=src python -m fund_performance.run_report --data data/test1            # with AI
PYTHONPATH=src python -m fund_performance.run_report --data data/test1 --offline  # no AI calls
```

Tests: `pytest -q` (AI calls are mocked; `pytest --run-live` runs the few live tests).

## Deploy on Render

1. In the Render dashboard: **New > Blueprint**, pick this repository. `render.yaml` sets up the web service
   (`python app.py`, free plan, deploys from `main`).
2. Enter the secrets when Render asks: `OPENAI_API_KEY`, and (recommended for a public link) `APP_USERNAME` and
   `APP_PASSWORD`. `RESEND_API_KEY` and `EMAIL_FROM` are only needed to email the report.
3. After a push to `main`, Render rebuilds and redeploys.

Runs are kept on the server's disk until the next deploy (Render's free plan has no permanent disk).

## Settings

| File | What it holds |
|---|---|
| `config/thresholds.yaml` | Rating thresholds and run limits (illustrative, to be agreed with the oversight team) |
| `config/models.yaml` | The model for each AI agent |
| `config/sources.yaml` | Approved web pages per fund and market, fetched by code |
| `config/settings.yaml` | Timeouts per AI step, and email (off by default; recipients set here only) |

Everything in `data/` is gitignored: the repository is public, so price files, factsheets and KIDs stay local.
