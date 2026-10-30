""" Stage 6B deployment safety: unique report folders under concurrency, the login and file access, the independent
AI switch, and the clean-up of old reports and cached files """
import asyncio
import os
from pathlib import Path
import socket
import time
import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "demo" / "sample_index_fund"


# 1. Report folders: one per review, never shared
def test_run_folders_are_unique_even_in_the_same_second(tmp_path, monkeypatch):
    from fund_performance import controller

    class Frozen(controller.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 30, 12, 0, 0)
    monkeypatch.setattr(controller, "datetime", Frozen)
    folders = {controller.new_run_dir(tmp_path) for _ in range(50)}
    assert len(folders) == 50 and all(f.name.startswith("20260930-120000-") for f in folders)


def test_concurrent_reviews_each_get_their_own_reports(tmp_path, monkeypatch):
    """ Two reviews started together (as two users would): separate folders, each report from its own inputs """
    from fund_performance.controller import run_review
    from fund_performance.report import page_texts
    other = tmp_path / "other"
    import shutil
    shutil.copytree(SAMPLE, other)
    profile = (other / "fund_profile.json").read_text().replace("Sample World Index Fund A Acc", "Second Test Fund")
    (other / "fund_profile.json").write_text(profile)

    async def both():
        return await asyncio.gather(run_review(SAMPLE, out_root=tmp_path / "runs", offline=True),
                                    run_review(other, out_root=tmp_path / "runs", offline=True))
    a, b = asyncio.run(both())
    assert a.run_dir != b.run_dir and a.pdf != b.pdf and a.executive_pdf != b.executive_pdf
    assert "Sample World Index Fund A Acc" in page_texts(a.executive_pdf)[0]
    assert "Second Test Fund" in page_texts(b.executive_pdf)[0]
    assert "Sample World Index Fund A Acc" not in page_texts(b.executive_pdf)[0]


# 2. The independent AI switch (off unless AI_RUNS_ENABLED is true)
@pytest.mark.parametrize("value, port, login, off", [
    (None, None, False, True),           # unset: off, even on your own computer
    ("false", None, False, True),
    ("true", None, False, False),        # on locally
    ("true", "10000", False, True),      # on a server without a login: still off
    ("true", "10000", True, False),      # on a server with the login: on
    ("false", "10000", True, True),      # the login alone never turns AI on
])
def test_ai_runs_need_the_switch_and_on_a_server_the_login(monkeypatch, value, port, login, off):
    from fund_performance import web
    for key, val in (("AI_RUNS_ENABLED", value), ("PORT", port), ("APP_USERNAME", "u" if login else None),
                     ("APP_PASSWORD", "p" if login else None)):
        monkeypatch.delenv(key, raising=False) if val is None else monkeypatch.setenv(key, val)
    assert web.ai_switched_off() is off


def test_with_ai_off_no_review_reaches_ai_but_offline_reviews_still_run(tmp_path, monkeypatch):
    from fund_performance import web
    from fund_performance.config import WebSettings
    monkeypatch.delenv("AI_RUNS_ENABLED", raising=False)
    limits = web.AiLimits(WebSettings(max_ai_runs_per_day=5, max_ai_runs_at_once=1), tmp_path / "count.json")
    called = []

    async def runner(*args, **kwargs):
        called.append(args)
        raise AssertionError("an AI review must not start")
    docs = asyncio.run(web.start_review("q", str(SAMPLE / "prices.csv"), str(SAMPLE / "factsheet.pdf"), None, [],
                                        None, False, limits, out_root=tmp_path, runner=runner))
    assert docs.message == web.AI_OFF and not called and limits.used_today() == 0
    demo_json = [str(SAMPLE / n) for n in ("fund_profile.json", "factsheet_performance.json", "peer.json")]
    assert web.run_offline(str(SAMPLE / "prices.csv"), demo_json)
    quick = asyncio.run(web.start_review("q", str(SAMPLE / "prices.csv"), None, None, [], demo_json, True, limits,
                                         out_root=tmp_path))
    assert quick.data is not None and quick.pdf and quick.executive                    # the Quick Demo still works
    assert not web.live_demo_allowed()


# 3. Clean-up of old reports
def test_old_run_folders_are_deleted_and_nothing_else(tmp_path):
    from fund_performance.web import prune_runs
    old, new = tmp_path / "20260101-120000-0123abcd", tmp_path / "20260930-120000-89abcdef"
    legacy, other = tmp_path / "20260101-120000", tmp_path / "keep-me"
    for d in (old, new, legacy, other):
        d.mkdir()
        (d / "report.pdf").write_bytes(b"%PDF")
    (tmp_path / "ai_runs_today.json").write_text("{}")
    now = time.time()
    for d in (old, legacy, other):
        os.utime(d, (now - 30 * 3600, now - 30 * 3600))
    assert sorted(prune_runs(tmp_path, 24, now)) == sorted([old.name, legacy.name])
    assert new.is_dir() and other.is_dir() and (tmp_path / "ai_runs_today.json").is_file()
    assert prune_runs(tmp_path / "missing", 24) == []


def test_the_page_cleans_gradios_file_cache():
    from fund_performance.config import load_settings
    from fund_performance.web import build_ui
    web = load_settings().web
    assert build_ui().delete_cache == (web.cache_cleanup_minutes * 60, int(web.keep_runs_hours * 3600))


# 4. The login and file access (a real server on a free port)
@pytest.fixture(scope="module")
def server():
    from fund_performance.web import build_ui
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    ui = build_ui()
    ui.queue()
    ui.launch(server_port=port, prevent_thread_lock=True, auth=("tester", "s3cret-pass"), quiet=True)
    yield f"http://127.0.0.1:{port}"
    ui.close()


def test_without_the_login_nothing_but_the_login_page_is_served(server, tmp_path):
    anon = requests.Session()
    assert anon.get(server + "/").status_code == 200                       # the login page (the health check)
    for path in ("/config", "/gradio_api/info", "/gradio_api/file=" + str(ROOT / ".env.example"),
                 "/gradio_api/file=/etc/passwd"):
        assert anon.get(server + path, allow_redirects=False).status_code in (401, 403), path
    f = tmp_path / "x.csv"
    f.write_text("Date,NAV\n2024-01-31,1\n")
    assert anon.post(server + "/gradio_api/upload", files={"files": f.open("rb")}).status_code == 401
    assert requests.post(server + "/login", data={"username": "tester", "password": "wrong"}).status_code == 400


def test_files_are_served_only_to_a_logged_in_user_and_only_from_gradios_cache(server, tmp_path):
    user = requests.Session()
    assert user.post(server + "/login", data={"username": "tester", "password": "s3cret-pass"}).status_code == 200
    f = tmp_path / "x.csv"
    f.write_text("Date,NAV\n2024-01-31,1\n")
    cached = user.post(server + "/gradio_api/upload", files={"files": f.open("rb")}).json()[0]
    assert user.get(server + "/gradio_api/file=" + cached).status_code == 200
    assert requests.get(server + "/gradio_api/file=" + cached, allow_redirects=False).status_code == 401
    for path in (ROOT / ".env.example", ROOT / "config" / "settings.yaml", ROOT / "runs", Path("/etc/passwd")):
        assert user.get(server + "/gradio_api/file=" + str(path)).status_code == 403, path   # even when logged in
