from agents import Agent, function_tool, ModelSettings
from messenger import send_email, push
import os

MODEL_NAME = os.getenv("NOTIFY_MODEL_NAME", "gpt-5.4-mini")
USE_EMAIL = os.getenv("USE_EMAIL", "true").lower() == "true"

settings = ModelSettings(tool_choice="required")


@function_tool
def send_notification(subject: str, text_body: str, html_body: str) -> str:
    """
    Send the output by email, or as a push notification if email is turned off

    Args:
        subject: The subject line
        text_body: The body as plain text
        html_body: The body as HTML
    """
    if USE_EMAIL:
        send_email(subject, text_body, html_body)
    else:
        push(f"Subject: {subject}\n\n{text_body}")
    return "Notification sent successfully"


INSTRUCTIONS = """
You are given a markdown document. Use your tool to send it, converting it into
a clean, well presented HTML email with a fitting subject line.
"""

notify_agent = Agent(name="Notify Agent", instructions=INSTRUCTIONS, tools=[send_notification], model=MODEL_NAME, model_settings=settings)
