from pathlib import Path
import requests
import os
import smtplib
from email.message import EmailMessage


EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_SMTP_SERVER = os.getenv("EMAIL_SMTP_SERVER")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")


def email_configured() -> bool:
    return all([EMAIL_ADDRESS, EMAIL_SMTP_SERVER, EMAIL_APP_PASSWORD])


def send_email(subject, text_body, html_body, attachment_path=None):
    msg = EmailMessage()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_ADDRESS
    msg["Subject"] = subject
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    if attachment_path:
        path = Path(attachment_path)
        msg.add_attachment(path.read_bytes(), maintype="application", subtype="pdf", filename=path.name)

    with smtplib.SMTP(EMAIL_SMTP_SERVER, 587) as server:
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
        server.send_message(msg)


pushover_user = os.getenv("PUSHOVER_USER")
pushover_token = os.getenv("PUSHOVER_TOKEN")
pushover_url = "https://api.pushover.net/1/messages.json"


def push_configured() -> bool:
    return all([pushover_user, pushover_token])


def push(message):
    print(f"Push: {message}")
    payload = {"user": pushover_user, "token": pushover_token, "message": message}
    requests.post(pushover_url, data=payload, timeout=15)
