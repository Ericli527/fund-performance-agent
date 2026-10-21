---
title: fund_report_agent
app_file: app.py
sdk: gradio
sdk_version: 6.14.0
---

# Fund Report Agent

A multi-agent app that analyses a fund's **performance and attribution** from uploaded
data, adds market context from up to **5 web searches**, and delivers a brief report as
a **PDF**, by **email** (PDF attached) and as a **Pushover** notification with a short summary.

Built with the [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) and Gradio.
Based on the structure of [Deep-Research-Agent](https://github.com/ericli527/Deep-Research-Agent).

## How it works

```
Question + uploaded files (Gradio UI)
   │
   ├─► file_parser.py     (Python)  reads CSV / Excel / PDF / Word / text
   ├─► calculator.py      (Python)  performance metrics + Brinson-Fachler attribution
   ├─► charts.py          (Python)  growth of 100 + attribution charts
   ├─► Planner Agent      (LLM)     plans up to 5 searches to explain the results
   ├─► Search Agent × ≤5  (LLM)     web search, run in parallel
   ├─► Writer Agent       (LLM)     key messages, committee action, section commentary
   ├─► report_builder.py  (Python)  report layout (HTML for the PDF, Markdown for app/email)
   ├─► pdf_builder.py     (Python)  HTML → PDF
   └─► Notify Agent       (LLM)     tools: send_email_tool (PDF attached), send_push_tool
```

### Report structure

Modelled on investment committee and manager performance reports: the conclusion first,
then the evidence.

| Page | Content |
|---|---|
| 1. Executive summary | Status rating, headline figures, key messages, returns by period (3M, 6M, 1Y, 3Y, 5Y, since start), top contributors and detractors, recommended committee action |
| 2. Performance and risk | Commentary, growth of 100 chart, drawdown chart, risk and return metrics |
| 3. Attribution | Commentary, summary of effects, attribution chart, full Brinson-Fachler table |
| 4. Context and appendix | Market context, outlook and risks to monitor, methodology, data sources, disclaimer |

Every page has a footer with the fund name, report date and page number.

### Design choices

- **Python does the maths, the LLM explains it.** All figures in the report come from
  pandas, so the LLM cannot make arithmetic mistakes. The writer is told not to invent numbers.
- **Search limit in code, not just the prompt.** The plan is cut to 5 searches even if the
  planner returns more.
- **Run context keeps files away from the LLM.** The PDF path is passed to the notify tools
  through the SDK's `RunContextWrapper`, so the model decides *what* to send but never handles the file.
- **Rule-based status, not an LLM opinion.** On track / Watch / Under review comes from a
  documented rule on annualised excess return, shown in the appendix.
- **Graceful failures.** A failed search is skipped; email or push without settings is
  reported as "skipped" instead of crashing.

## Data formats

Column names are matched without regard to case. See `samples/` for examples.

**NAV / price series** (CSV or an Excel sheet), used for performance and risk metrics:

| date | fund | benchmark |
|---|---|---|
| 2024-09-30 | 100.00 | 100.00 |

Values are NAV, price or index levels (not returns). Daily, weekly, monthly or quarterly data are detected automatically.

**Attribution data**, used for Brinson-Fachler attribution:

| sector | fund_weight | benchmark_weight | fund_return | benchmark_return |
|---|---|---|---|---|
| Information Technology | 28.0 | 24.0 | 14.2 | 12.5 |

Use either percentages (weights sum to 100) or decimals (weights sum to 1) for all four columns.

**Documents** (PDF, Word, text, or any unrecognised table) are passed to the writer as reference.

## Metrics

- Total and annualised return, annualised volatility, Sharpe ratio, max drawdown
- Excess return, tracking error, information ratio, beta
- Allocation, selection and interaction effects by segment (Brinson-Fachler)

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then add your OPENAI_API_KEY (email and Pushover are optional)
python app.py
```

Upload the two files in `samples/` to try it.

> Uploaded data is sent to OpenAI. Do not upload confidential client data.
> Reports are for demonstration only and are not investment advice.
