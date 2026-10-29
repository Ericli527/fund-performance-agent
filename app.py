""" Fund performance review: the web app (step 11). Run locally with `python app.py`; Render runs the same.

The app lives in the package src/fund_performance (web.py for the page, controller.py for the review).
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from fund_performance.agents.base import load_env  # noqa: E402
from fund_performance.web import launch  # noqa: E402

if __name__ == "__main__":
    load_env()          # OPENAI_API_KEY and other settings from .env (Render sets them as environment variables)
    launch()
