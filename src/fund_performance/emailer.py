""" Emails the finished report (step 10). Plain code, not an AI agent, and off by default.

Sends through Resend over HTTPS, the same setup as the old app had: Render's free plan blocks email
(SMTP) ports. The key is RESEND_API_KEY in .env; the sender is `email.sender` in config/settings.yaml, else
EMAIL_FROM in .env, else Resend's test sender (which only delivers to the Resend account's own address).
Recipients come only from the EMAIL_TO environment variable (comma-separated; in .env or Render's settings), never
from the repository, the documents, the web or an AI agent. Only the PDF is attached: it holds public data.
"""
import base64
import os
from pathlib import Path
from typing import Callable
import requests
from fund_performance.config import EmailSettings

RESEND_URL = "https://api.resend.com/emails"
TEST_SENDER = "Fund Report Agent <onboarding@resend.dev>"
TIMEOUT_SECONDS = 20
PostFn = Callable[..., requests.Response]


def recipients() -> list[str]:
    """ The addresses in EMAIL_TO, comma-separated """
    return [a.strip() for a in os.getenv("EMAIL_TO", "").split(",") if a.strip()]


def build_payload(pdf: Path, settings: EmailSettings, fund_name: str, as_of_date: str, to: list[str],
                  filename: str | None = None) -> dict:
    text = (f"The draft fund performance review for {fund_name} (figures to {as_of_date}) is attached.\n\n"
            "It is a draft for oversight review: the verdict is final only when signed by the reviewer.\n"
            "Prepared from public data only.")
    return {"from": settings.sender or os.getenv("EMAIL_FROM") or TEST_SENDER, "to": to,
            "subject": settings.subject.format(fund_name=fund_name, as_of_date=as_of_date),
            "text": text, "html": "<p>" + text.replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>",
            "attachments": [{"filename": filename or pdf.name, "content": base64.b64encode(pdf.read_bytes()).decode()}]}


def send_report(pdf: Path, settings: EmailSettings, fund_name: str, as_of_date: str,
                post: PostFn = requests.post, filename: str | None = None) -> str:
    """ Send the PDF to the configured recipients, attached as `filename` (default: its own name). Returns a line
    for the run log; never raises, so a failed email does not lose the report (it is already saved) """
    if not settings.enabled:
        return "Email: off (config/settings.yaml)"
    key = os.getenv("RESEND_API_KEY")
    if not key:
        return "Email: not sent, RESEND_API_KEY is missing from .env"
    to = recipients()
    if not to:
        return "Email: not sent, EMAIL_TO is not set"
    bad = [a for a in to if "@" not in a]
    if bad:
        return f"Email: not sent, EMAIL_TO has an entry that is not an email address ({len(bad)})"
    try:
        response = post(RESEND_URL, json=build_payload(pdf, settings, fund_name, as_of_date, to, filename),
                        headers={"Authorization": f"Bearer {key}"}, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as e:
        return f"Email: not sent, could not reach Resend ({type(e).__name__})"
    if not response.ok:
        try:
            reason = response.json().get("message", response.text)
        except ValueError:
            reason = response.text
        return f"Email: not sent, Resend returned {response.status_code}: {str(reason)[:160]}"
    return f"Email: sent to {len(to)} recipient(s) from EMAIL_TO"
