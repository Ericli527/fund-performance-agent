""" Emails the finished report (step 10). Plain code, not an AI agent, and off by default.

Recipients come from config/settings.yaml only, never from the documents, the web or an AI agent. The SMTP
login comes from .env (FUND_SMTP_USER, FUND_SMTP_PASSWORD). Only the PDF is attached: it holds public data.
"""
from email.message import EmailMessage
import os
from pathlib import Path
import smtplib
from typing import Callable
from fund_performance.config import EmailSettings

SmtpFactory = Callable[[str, int], smtplib.SMTP]


def build_message(pdf: Path, settings: EmailSettings, fund_name: str, as_of_date: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = settings.subject.format(fund_name=fund_name, as_of_date=as_of_date)
    msg["From"] = settings.sender
    msg["To"] = ", ".join(settings.recipients)
    msg.set_content(f"The draft fund performance review for {fund_name} (figures to {as_of_date}) is attached.\n\n"
                    "It is a draft for oversight review: the verdict is final only when signed by the reviewer.\n"
                    "Prepared from public data only.")
    msg.add_attachment(pdf.read_bytes(), maintype="application", subtype="pdf", filename=pdf.name)
    return msg


def send_report(pdf: Path, settings: EmailSettings, fund_name: str, as_of_date: str,
                smtp: SmtpFactory = smtplib.SMTP) -> str:
    """ Send the PDF to the configured recipients. Returns a line for the run log; never raises, so a failed
    email does not lose the report (it is already saved) """
    if not settings.enabled:
        return "Email: off (config/settings.yaml)"
    user, password = os.getenv("FUND_SMTP_USER"), os.getenv("FUND_SMTP_PASSWORD")
    if not (user and password):
        return "Email: not sent, FUND_SMTP_USER or FUND_SMTP_PASSWORD is missing from .env"
    try:
        with smtp(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(build_message(pdf, settings, fund_name, as_of_date))
    except (smtplib.SMTPException, OSError) as e:
        return f"Email: not sent ({type(e).__name__}: {str(e)[:120]})"
    return f"Email: sent to {len(settings.recipients)} recipient(s) from config/settings.yaml"
