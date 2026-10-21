---
title: my_new_agent
app_file: app.py
sdk: gradio
sdk_version: 6.14.0
---

# My New Agent

A starter template for a multi-agent app, built with the
[OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) and Gradio.
Based on the structure of [Deep-Research-Agent](https://github.com/ericli527/Deep-Research-Agent).

## How it works

```
User query (Gradio UI)
      │
      ▼
 AgentManager ──► Planner Agent  → TaskPlan (HOW_MANY_TASKS tasks)
      │
      ├──► Worker Agent × N     (run in parallel; failed tasks are skipped)
      │
      ├──► Writer Agent         → FinalOutput (summary + markdown)
      │
      └──► Notify Agent         → email or Pushover (optional, USE_NOTIFY=true)
```

| File | Role |
|---|---|
| `app.py` | Gradio UI and entry point |
| `agent_manager.py` | Orchestrator: runs the steps in order and streams status updates |
| `planner_agent.py` | Breaks the query into tasks (structured output) |
| `worker_agent.py` | Completes one task with tools |
| `writer_agent.py` | Combines results into the final output |
| `notify_agent.py` | Sends the output by email or push notification |
| `messenger.py` | SMTP email and Pushover helpers |
| `styles.py` | UI styling, header and example prompts |

Look for `TODO` comments to customise each agent.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then add your OPENAI_API_KEY
python app.py
```
