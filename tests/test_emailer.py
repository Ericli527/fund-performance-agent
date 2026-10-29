""" Emailing the report (step 10): plain code, off by default, recipients from settings only """
from email.message import EmailMessage
import pytest
from fund_performance.config import EmailSettings, load_settings
from fund_performance.emailer import send_report

ON = EmailSettings(enabled=True, recipients=["oversight@example.com", "director@example.com"],
                   sender="reviews@example.com", smtp_host="smtp.example.com", smtp_port=587,
                   subject="Fund performance review (draft): {fund_name}, figures to {as_of_date}")


class FakeSMTP:
    sent: list[EmailMessage] = []

    def __init__(self, host, port):
        self.host, self.port, self.calls = host, port, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user))

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-1.4 test")
    return path


def test_email_is_off_by_default():
    s = load_settings().email
    assert s.enabled is False and s.recipients == []


def test_off_means_nothing_is_sent(pdf):
    FakeSMTP.sent = []
    line = send_report(pdf, load_settings().email, "Fund", "30 Sep 2026", smtp=FakeSMTP)
    assert line == "Email: off (config/settings.yaml)" and FakeSMTP.sent == []


def test_sends_to_the_configured_recipients_only(pdf, monkeypatch):
    monkeypatch.setenv("FUND_SMTP_USER", "user")
    monkeypatch.setenv("FUND_SMTP_PASSWORD", "secret")
    FakeSMTP.sent = []
    line = send_report(pdf, ON, "Fidelity Index US Fund P Accumulation", "30 Sep 2026", smtp=FakeSMTP)
    msg = FakeSMTP.sent[0]
    assert line == "Email: sent to 2 recipient(s) from config/settings.yaml"
    assert msg["To"] == "oversight@example.com, director@example.com"
    assert msg["Subject"] == "Fund performance review (draft): Fidelity Index US Fund P Accumulation, figures to 30 Sep 2026"
    assert [p.get_filename() for p in msg.iter_attachments()] == ["report.pdf"]
    assert "secret" not in msg.as_string()


def test_missing_login_or_smtp_error_never_raises(pdf, monkeypatch):
    monkeypatch.delenv("FUND_SMTP_USER", raising=False)
    assert "FUND_SMTP_USER or FUND_SMTP_PASSWORD is missing" in send_report(pdf, ON, "F", "d", smtp=FakeSMTP)
    monkeypatch.setenv("FUND_SMTP_USER", "user")
    monkeypatch.setenv("FUND_SMTP_PASSWORD", "secret")

    class Down(FakeSMTP):
        def __init__(self, host, port):
            raise OSError("connection refused")
    assert send_report(pdf, ON, "F", "d", smtp=Down).startswith("Email: not sent (OSError")


def test_email_settings_are_checked():
    with pytest.raises(ValueError, match="recipients, sender or smtp_host is missing"):
        EmailSettings(**(ON.model_dump() | {"recipients": []}))
    with pytest.raises(ValueError, match="not an email address"):
        EmailSettings(**(ON.model_dump() | {"recipients": ["oversight team"]}))
