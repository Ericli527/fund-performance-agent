from dataclasses import dataclass
from agents import Agent, RunContextWrapper, function_tool, ModelSettings
from messenger import send_email, push, email_configured, push_configured, EmailError
import os

MODEL_NAME = os.getenv("NOTIFY_MODEL_NAME", "gpt-5.4-mini")


@dataclass
class NotifyContext:
    """ Local data the tools can use but the LLM never sees """
    pdf_path: str


@function_tool
def send_email_tool(ctx: RunContextWrapper[NotifyContext], subject: str, text_body: str, html_body: str) -> str:
    """
    Email the report, with the PDF version attached

    Args:
        subject: The subject of the email
        text_body: The body of the email as plain text
        html_body: The body of the email as HTML
    """
    if not email_configured():
        return "Email skipped: email settings are not configured"
    # Failures come back as text, so the agent reports them instead of the run crashing
    try:
        send_email(subject, text_body, html_body, attachment_path=ctx.context.pdf_path)
    except EmailError as e:
        return f"Email failed: {e}. Do not retry."
    return "Email sent successfully with the PDF attached"


@function_tool
def send_push_tool(message: str) -> str:
    """
    Send a short push notification to the user's phone

    Args:
        message: The notification text, under 1000 characters
    """
    if not push_configured():
        return "Push skipped: Pushover settings are not configured"
    try:
        push(message[:1000])
    except Exception as e:
        return f"Push failed: {e.__class__.__name__}. Do not retry."
    return "Push notification sent successfully"


INSTRUCTIONS = """
You deliver a finished fund report. You are given the short summary and the full report
in markdown. Do both of these:
1. Use send_email_tool to send a clean, well presented HTML email with a fitting subject.
   Open with the short summary, then the report. Mention that the PDF is attached.
2. Use send_push_tool to send the short summary as a push notification.
Call each tool once. If a tool says it failed or was skipped, do not call it again.
Then reply with one line saying what was sent, and the reason for anything that failed.
"""

notify_agent = Agent[NotifyContext](
    name="Notify Agent",
    instructions=INSTRUCTIONS,
    tools=[send_email_tool, send_push_tool],
    model=MODEL_NAME,
    model_settings=ModelSettings(tool_choice="required"),
)
