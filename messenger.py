from pathlib import Path
import base64
import requests
import os
import smtplib
from email.message import EmailMessage


EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_SMTP_SERVER = os.getenv("EMAIL_SMTP_SERVER")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
# Recipients, comma-separated; empty means send the report to yourself
EMAIL_TO = [a.strip() for a in os.getenv("EMAIL_TO", "").split(",") if a.strip()] or [a for a in [EMAIL_ADDRESS] if a]

# Resend sends over HTTPS, which works on hosts that block email (SMTP) ports, such as Render's free plan
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_URL = "https://api.resend.com/emails"
# Resend's test sender, which can only deliver to the email address of your Resend account
EMAIL_FROM = os.getenv("EMAIL_FROM", "Fund Report Agent <onboarding@resend.dev>")

TIMEOUT_SECONDS = 20


class EmailError(Exception):
    """ Sending failed, with a reason the agent can report """


def email_configured() -> bool:
    if RESEND_API_KEY:
        return bool(EMAIL_TO)
    return all([EMAIL_ADDRESS, EMAIL_SMTP_SERVER, EMAIL_APP_PASSWORD])


def send_email(subject, text_body, html_body, attachment_path=None):
    """ Send through Resend when its key is set, otherwise through SMTP """
    if RESEND_API_KEY:
        _send_resend(subject, text_body, html_body, attachment_path)
    else:
        _send_smtp(subject, text_body, html_body, attachment_path)


def _send_resend(subject, text_body, html_body, attachment_path):
    payload = {"from": EMAIL_FROM, "to": EMAIL_TO, "subject": subject, "html": html_body, "text": text_body}
    if attachment_path:
        path = Path(attachment_path)
        payload["attachments"] = [{"filename": path.name, "content": base64.b64encode(path.read_bytes()).decode()}]
    try:
        response = requests.post(RESEND_URL, json=payload, timeout=TIMEOUT_SECONDS,
                                 headers={"Authorization": f"Bearer {RESEND_API_KEY}"})
    except requests.RequestException as e:
        raise EmailError(f"could not reach Resend ({e.__class__.__name__})") from e
    if not response.ok:
        try:
            reason = response.json().get("message", response.text)
        except ValueError:
            reason = response.text
        raise EmailError(f"Resend returned {response.status_code}: {reason}")


def _send_smtp(subject, text_body, html_body, attachment_path):
    msg = EmailMessage()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = ", ".join(EMAIL_TO)
    msg["Subject"] = subject
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    if attachment_path:
        path = Path(attachment_path)
        msg.add_attachment(path.read_bytes(), maintype="application", subtype="pdf", filename=path.name)

    try:
        with smtplib.SMTP(EMAIL_SMTP_SERVER, 587, timeout=TIMEOUT_SECONDS) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
            server.send_message(msg)
    except (OSError, smtplib.SMTPException) as e:
        raise EmailError(f"SMTP failed ({e.__class__.__name__}: {e}). The host may block email ports; "
                         "set RESEND_API_KEY to send over HTTPS instead") from e


pushover_user = os.getenv("PUSHOVER_USER")
pushover_token = os.getenv("PUSHOVER_TOKEN")
pushover_url = "https://api.pushover.net/1/messages.json"


def push_configured() -> bool:
    return all([pushover_user, pushover_token])


def push(message):
    print(f"Push: {message}")
    payload = {"user": pushover_user, "token": pushover_token, "message": message}
    response = requests.post(pushover_url, data=payload, timeout=15)
    response.raise_for_status()
