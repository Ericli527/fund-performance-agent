---
title: fund_performance_review
app_file: app.py
sdk: gradio
sdk_version: 6.30.0
---

# Fund Performance Review

A web app that drafts an **investment oversight review** of a fund as a 5-page PDF: is the fund doing what it
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
   ├─ Research                approved pages fetched by code + up to 3 web searches (AI), vetted by code
   ├─ Findings and actions    written by code
   ├─ Market context (AI)     checked by code, then by the Evaluator Agent (AI)
   ├─ Reporting Agents (AI)   draft the conclusion for the board, the analyst and the manager meeting, in parallel
   ├─ Judge (AI) + code       code checks every figure; the Judge marks a checklist; code scores and picks the best,
   │                          or sends the drafts back once; code's own conclusion is the fallback
   └─ Report (code)           5-page PDF: summary, evidence dashboard, mandate and performance, value and fees,
                              appendix; optional email (Resend)
```

Every run is saved in `runs/<timestamp>/`: `report.pdf`, `facts.json`, `run_log.txt` and `log.json` (each step,
its inputs and its outputs).

## Run it on your computer

```bash
pip install -r requirements.txt
cp .env.example .env            # add your OPENAI_API_KEY
python app.py                   # opens on http://127.0.0.1:7860
```

Click **Use the demo files (made-up fund)** and **Run the review** to try it without any AI calls. With
`APP_USERNAME` and `APP_PASSWORD` set in `.env`, the page asks for them before it opens; on your own computer you
can leave them blank (no login).

For a real fund: add the price file and the factsheet (KID and peer factsheets optional; for an S&P 500 fund the
approved peers are used), untick **Offline** and click **Run the review**; code checks every value the agent read.
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
