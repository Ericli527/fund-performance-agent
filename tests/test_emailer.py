""" Emailing the report (step 10): plain code, off by default, Resend over HTTPS, recipients from EMAIL_TO only """
from pathlib import Path
import base64
import pytest
import requests
from fund_performance.config import EmailSettings, load_settings
from fund_performance.emailer import RESEND_URL, TEST_SENDER, send_report

ON = EmailSettings(enabled=True, sender="", subject="Fund performance review (draft): {fund_name}, figures to {as_of_date}")


class FakePost:
    """ Stands in for requests.post """
    def __init__(self, status=200, body=None, error=None):
        self.status, self.body, self.error, self.calls = status, body or {"id": "x"}, error, []

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if self.error:
            raise self.error
        response = requests.Response()
        response.status_code = self.status
        response._content = __import__("json").dumps(self.body).encode()
        return response


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-1.4 test")
    return path


@pytest.fixture
def resend_key(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("EMAIL_TO", "oversight@example.com, director@example.com")
    monkeypatch.delenv("EMAIL_FROM", raising=False)


def test_email_is_off_by_default_and_has_no_recipients_in_the_repo():
    s = load_settings().email
    assert s.enabled is False and "recipients" not in EmailSettings.model_fields
    assert "@" not in (Path(__file__).resolve().parents[1] / "config" / "settings.yaml").read_text().split("email:")[1]


def test_off_means_nothing_is_sent(pdf, resend_key):
    post = FakePost()
    assert send_report(pdf, load_settings().email, "Fund", "30 Sep 2026", post=post) == "Email: off (config/settings.yaml)"
    assert post.calls == []


def test_sends_through_resend_to_the_email_to_recipients_only(pdf, resend_key):
    post = FakePost()
    line = send_report(pdf, ON, "Fidelity Index US Fund P Accumulation", "30 Sep 2026", post=post)
    call = post.calls[0]
    assert line == "Email: sent to 2 recipient(s) from EMAIL_TO"
    assert call["url"] == RESEND_URL and call["headers"] == {"Authorization": "Bearer re_test"}
    assert call["json"]["to"] == ["oversight@example.com", "director@example.com"]
    assert call["json"]["from"] == TEST_SENDER                                   # no sender set anywhere
    assert call["json"]["subject"] == ("Fund performance review (draft): Fidelity Index US Fund P Accumulation, "
                                       "figures to 30 Sep 2026")
    attachment = call["json"]["attachments"][0]
    assert attachment["filename"] == "report.pdf" and base64.b64decode(attachment["content"]) == b"%PDF-1.4 test"
    assert "re_test" not in str(call["json"])                                   # the key is only in the header


def test_sender_from_settings_then_email_from(pdf, resend_key, monkeypatch):
    monkeypatch.setenv("EMAIL_FROM", "Fund Report <reports@old-app.example>")
    post = FakePost()
    send_report(pdf, ON, "F", "d", post=post)
    send_report(pdf, ON.model_copy(update={"sender": "Reviews <reviews@example.com>"}), "F", "d", post=post)
    assert [c["json"]["from"] for c in post.calls] == ["Fund Report <reports@old-app.example>",
                                                       "Reviews <reviews@example.com>"]


def test_failures_never_raise(pdf, resend_key, monkeypatch):
    assert send_report(pdf, ON, "F", "d", post=FakePost(422, {"message": "domain not verified"})) == \
        "Email: not sent, Resend returned 422: domain not verified"
    assert send_report(pdf, ON, "F", "d", post=FakePost(error=requests.ConnectionError())) == \
        "Email: not sent, could not reach Resend (ConnectionError)"
    monkeypatch.delenv("RESEND_API_KEY")
    assert send_report(pdf, ON, "F", "d", post=FakePost()) == "Email: not sent, RESEND_API_KEY is missing from .env"


def test_missing_or_bad_email_to_is_not_sent(pdf, resend_key, monkeypatch):
    monkeypatch.delenv("EMAIL_TO")
    assert send_report(pdf, ON, "F", "d", post=FakePost()) == "Email: not sent, EMAIL_TO is not set"
    monkeypatch.setenv("EMAIL_TO", "oversight team")
    assert send_report(pdf, ON, "F", "d", post=FakePost()).startswith("Email: not sent, EMAIL_TO has an entry")


def test_the_attachment_can_carry_a_readable_name(pdf, resend_key):
    post = FakePost()
    send_report(pdf, ON, "Fund", "30 Sep 2026", post=post, filename="Fund_Executive_Report_2026-09-30.pdf")
    assert post.calls[0]["json"]["attachments"][0]["filename"] == "Fund_Executive_Report_2026-09-30.pdf"
    assert pdf.name == "report.pdf"                                             # the file itself keeps its name
