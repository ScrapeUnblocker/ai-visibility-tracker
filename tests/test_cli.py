from __future__ import annotations

import io
import json
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import (
    BEHIND,
    ENV,
    GOOD,
    MISSING,
    NOW,
    FakeClient,
    FakeHttp,
    FakeSMTP,
    ai_mode_json,
    chatgpt_json,
    gemini_json,
    same_answers,
)
from scrapeunblocker import AuthenticationError, InvalidRequestError, ServerError

import ai_visibility_tracker.sinks as sinks
from ai_visibility_tracker.cli import build_parser, main
from ai_visibility_tracker.sinks import HEADER, SheetSink

ACCOUNT = json.dumps(
    {"client_email": "bot@p.iam.test", "private_key": "k", "token_uri": "https://t/token"}
)


@pytest.fixture(autouse=True)
def no_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(SheetSink, "assertion", lambda self: "jwt")


class Runner:
    def __init__(self, config_path: Path):
        self.config = config_path
        self.http = FakeHttp()
        self.env: dict[str, str] = dict(ENV)
        self.client = same_answers()

    def __call__(self, *args: str, now=NOW, client: FakeClient | None = None) -> tuple[int, str]:
        if client is not None:
            self.client = client
        out, err = io.StringIO(), io.StringIO()
        code = main(
            [*args[:1], "-c", str(self.config), "--env-file", "none.env", *args[1:]],
            environ=dict(self.env),
            client_factory=lambda env: self.client,
            http_factory=lambda: self.http,
            now=now,
            clock=lambda: now.isoformat(),
            out=out,
            err=err,
        )
        return code, out.getvalue() + err.getvalue()

    @property
    def chat(self) -> list[tuple[str, Any]]:
        return self.http.chat_posts

    def state(self) -> dict[str, Any]:
        return json.loads((self.config.parent / "state" / "visibility.json").read_text("utf-8"))


@pytest.fixture
def run(write_config: Callable[..., Path]) -> Runner:
    return Runner(write_config())


def test_parser() -> None:
    args = build_parser().parse_args(
        ["run", "--dry-run", "--force", "--engine", "gemini", "--prompt", "skates"]
    )
    assert (args.command, args.dry_run, args.force) == ("run", True, True)
    assert args.engine == ["gemini"] and args.prompt == ["skates"]
    args = build_parser().parse_args(["ask", "best skates", "--country", "gb", "--show-answer"])
    assert (args.question, args.country, args.show_answer) == ("best skates", "gb", True)
    assert build_parser().parse_args(["digest", "--force"]).force
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "--engine", "bing"])


def test_first_run_then_nothing_new(run: Runner) -> None:
    code, out = run("run")
    assert code == 0, out
    assert "6 API call(s)" in out
    assert len(run.client.calls) == 6
    assert "Delivered to slack, discord, webhook: AI visibility · Acme: named in 6 of 6" in out
    assert [u.split("/")[2] for u, _ in run.chat] == [
        "hooks.slack.test",
        "discord.test",
        "hook.test",
    ]
    slack = run.chat[0][1]["text"]
    assert "*best rocket skates for beginners*" in slack
    assert "• ChatGPT: named #1 of 3 · your site cited" in slack
    # "Globex alternatives": Globex is the subject, so it isn't ranked
    assert "*Globex alternatives for small teams*\n• ChatGPT: named #1 of 2" in slack
    state = run.state()
    assert len(state["checks"]) == 6 and len(state["baseline"]) == 6
    assert "No changes" not in out

    # second run, same day: no API calls, nothing sent
    posts = len(run.http.requests)
    code, out = run("run")
    assert code == 0
    assert "0 API call(s)" in out and "No changes to deliver." in out
    assert len(run.client.calls) == 6
    assert len(run.http.requests) == posts


def test_next_day_change_is_rechecked_and_sent_once(run: Runner) -> None:
    run("run")
    day2 = NOW + timedelta(days=1)
    behind = FakeClient(
        {
            "chatgpt": [chatgpt_json(BEHIND)],
            "gemini": [gemini_json(GOOD, ["https://acme.test/p"])],
            "google_ai_mode": [ai_mode_json(GOOD, ["https://acme.test/"])],
        }
    )
    code, out = run("run", now=day2, client=behind)
    assert code == 0, out
    # 6 asks + 2 rechecks for the two ChatGPT prompts that changed
    assert len(behind.calls) == 8
    assert "recheck confirmed" in out
    alert = run.chat[3][1]["text"]  # Slack, then Discord, the webhook, and the digest
    assert "Wed 18 Nov 2026 · 3 changes" in alert
    assert run.chat[6][1]["text"].startswith("👀 *AI visibility weekly · Acme*")
    assert (
        "• ChatGPT: 🔴 Globex is now named before you (you: #2 of 2); 🔴 your site is no " in alert
    )
    assert "• ChatGPT: 🔴 your site is no longer cited" in alert

    posts = len(run.chat)
    code, out = run("run", now=day2)
    assert "No changes to deliver." in out
    assert len(run.chat) == posts


def test_recheck_that_disagrees_sends_nothing(run: Runner) -> None:
    run("run")
    flip = FakeClient(
        {
            "chatgpt": [chatgpt_json(MISSING), chatgpt_json(GOOD, ["acme.test"])],
            "gemini": [gemini_json(GOOD, ["https://acme.test/p"])],
            "google_ai_mode": [ai_mode_json(GOOD, ["https://acme.test/"])],
        }
    )
    code, out = run("run", "--prompt", "rocket", now=NOW + timedelta(days=1), client=flip)
    assert code == 0, out
    assert "recheck answer disagrees, so no alert" in out
    assert "No changes to deliver." in out
    assert len(flip.calls) == 4


def test_dry_run_sends_and_saves_nothing(run: Runner) -> None:
    code, out = run("run", "--dry-run")
    assert code == 0
    assert "Dry run: would deliver AI visibility · Acme: named in 6 of 6 answers" in out
    assert "--- slack ---" in out and "--- webhook ---" in out
    assert "Dry run: nothing was sent or saved." in out
    assert run.http.requests == []
    assert not (run.config.parent / "state" / "visibility.json").exists()


def test_failed_delivery_is_retried_without_new_calls(run: Runner) -> None:
    run.http.fail = {"slack.test": 500, "discord.test": 500, "hook.test": 500}
    code, out = run("run")
    assert code == 1
    assert "Not delivered anywhere" in out
    assert run.state()["baseline"] == {}
    run.http.fail = {}
    code, out = run("run")
    assert code == 0
    assert "0 API call(s)" in out
    assert "Delivered to slack, discord, webhook: AI visibility · Acme: named in 6 of 6" in out


def test_no_alert_destination_waits(run: Runner) -> None:
    run.env = {"SCRAPEUNBLOCKER_KEY": "k"}
    code, out = run("run")
    assert code == 0
    assert "not set up, skipped: sheet, slack, discord, webhook, email" in out
    assert "Waiting: AI visibility · Acme" in out
    assert "6 rows wait for the Google Sheet" in out
    assert run.state()["baseline"] == {}


def test_sheet_gets_every_answer_once(run: Runner) -> None:
    run.env.update(GOOGLE_SHEET_ID="sheet1", GOOGLE_SERVICE_ACCOUNT_JSON=ACCOUNT)
    code, out = run("run")
    assert code == 0, out
    assert "Google Sheet: appended 6 rows to Answers." in out
    rows = run.http.tabs["Answers"]
    assert rows[0] == HEADER
    assert [r[4] for r in rows[1:4]] == ["ChatGPT", "Gemini", "Google AI Mode"]
    assert all(c["sheet"] for c in run.state()["checks"])
    run("run")
    assert len(run.http.tabs["Answers"]) == 7


def test_sheet_failure_keeps_rows_for_next_run(run: Runner) -> None:
    run.env.update(GOOGLE_SHEET_ID="sheet1", GOOGLE_SERVICE_ACCOUNT_JSON=ACCOUNT)
    run.http.fail = {":append": 503}
    code, out = run("run")
    assert code == 1
    assert "The rows are written on the next run." in out
    run.http.fail = {}
    code, out = run("run")
    assert "appended 6 rows" in out


def test_errors_and_permanent_refusal(run: Runner) -> None:
    client = FakeClient(
        {
            "chatgpt": [InvalidRequestError("prompt too long", status_code=400)],
            "gemini": [ServerError("no answer", status_code=502)],
            "google_ai_mode": [ai_mode_json(GOOD)],
        }
    )
    run.env["GITHUB_ACTIONS"] = "true"
    code, out = run("run", client=client)
    assert code == 1  # a refused prompt needs a config fix
    assert "no answer: ChatGPT refused the prompt" in out
    assert "::warning title=ChatGPT not asked::" in out
    assert "::notice title=Gemini not asked::" in out
    assert "named in 2 of 2 answers" in out
    # the failed ones are asked again on the next run
    code, out = run("run", client=same_answers())
    assert "4 API call(s)" in out


def test_auth_error_stops(run: Runner) -> None:
    client = FakeClient(
        {
            e: [AuthenticationError("bad key", status_code=401)]
            for e in ("chatgpt", "gemini", "google_ai_mode")
        }
    )
    code, out = run("run", client=client)
    assert code == 2
    assert "AuthenticationError" in out


def test_missing_key(run: Runner) -> None:
    run.env = {}
    code, out = run("run")
    assert code == 2
    assert "set SCRAPEUNBLOCKER_KEY" in out


def test_digest_goes_out_once_a_week(run: Runner, monkeypatch: pytest.MonkeyPatch) -> None:
    run.env.update(SMTP_HOST="smtp.test", EMAIL_TO="me@x.test", EMAIL_FROM="t@x.test")
    monkeypatch.setattr(sinks, "_connect", FakeSMTP)
    run("run")  # Tuesday: first day, no digest yet
    assert FakeSMTP.sent == []
    code, out = run("run", now=NOW + timedelta(days=1))
    assert "Weekly digest delivered to slack, email" in out
    assert FakeSMTP.sent[0]["Subject"].startswith("AI visibility weekly · Acme: named in 100%")
    assert run.state()["digest_week"] == "2026-W47"
    code, out = run("run", now=NOW + timedelta(days=2))
    assert "Weekly digest" not in out
    code, out = run("digest", now=NOW + timedelta(days=2))
    assert "went out already" in out
    code, out = run("digest", "--dry-run", "--force", now=NOW + timedelta(days=2))
    assert "Dry run: would send the weekly digest" in out
    assert len(FakeSMTP.sent) == 1


def test_status(run: Runner) -> None:
    code, out = run("status")
    assert code == 0
    assert "not asked yet" in out
    run("run")
    code, out = run("status")
    assert "ChatGPT         2026-11-17: named #1 of 3 · your site cited" in out
    assert "named in 1 of 1 in 7 days" in out


def test_ask(run: Runner) -> None:
    code, out = run("ask", "best skates", "--engine", "chatgpt", "--show-answer")
    assert code == 0
    assert "ChatGPT (US) · web search: yes" in out
    assert "brands named: Acme #1, Globex #2, Initech #3" in out
    assert "first named in: “For beginners, my top pick is Acme.”" in out
    assert "API calls used: 1. Nothing was saved." in out
    assert not (run.config.parent / "state").exists()


def test_test_destinations(run: Runner) -> None:
    run.env.update(GOOGLE_SHEET_ID="sheet1", GOOGLE_SERVICE_ACCOUNT_JSON=ACCOUNT)
    code, out = run("test-destinations")
    assert code == 0
    assert (
        "sheet    ok, tab 'Answers' created with its header row (shared with bot@p.iam.test)" in out
    )
    assert "slack    ok, test message sent" in out
    assert "email    skipped (SMTP_HOST and EMAIL_TO not set)" in out
    assert run.client.calls == []


def test_changed_brand_needs_a_fresh_state(run: Runner, write_config) -> None:
    run("run")
    from conftest import CONFIG

    run.config = write_config(CONFIG.replace("name: Acme", "name: Acme2"))
    code, out = run("run")
    assert code == 2
    assert "tracks 'Acme'" in out
