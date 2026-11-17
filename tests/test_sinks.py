from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

import pytest
from conftest import ENV, FakeHttp, FakeSMTP

from ai_visibility_tracker.config import Config
from ai_visibility_tracker.messages import PairReport, build_alert
from ai_visibility_tracker.process import Check
from ai_visibility_tracker.sinks import (
    HEADER,
    DeliveryError,
    DiscordSink,
    EmailSink,
    SheetSink,
    SlackSink,
    SmtpSettings,
    WebhookSink,
    build_destinations,
    load_service_account,
    sheet_id,
    sheet_row,
)

CHECK = Check(
    round="2026-11-17T07:00:00+00:00",
    at="2026-11-17T07:00:21+00:00",
    day="2026-11-17",
    prompt="p1",
    engine="google_ai_mode",
    sample=1,
    named=True,
    rank=2,
    brands={"Globex": 1, "Acme": 2},
    ahead=["Globex"],
    cited=True,
    sites=["forum.test", "acme.test"],
    excerpt="-Acme is lighter",
)
ACCOUNT = {"client_email": "bot@proj.iam.test", "private_key": "k", "token_uri": "https://t/token"}


def alert(config: Config):
    return build_alert(config, [PairReport(config.prompts[0], "chatgpt", [CHECK], None)], NOW)


NOW = datetime(2026, 11, 17, 7, 0, tzinfo=UTC)


def test_slack_payload(config: Config) -> None:
    http = FakeHttp()
    SlackSink("https://hooks.slack.test/x", http).send(alert(config))
    body = http.posts_to("slack")[0]
    assert body["unfurl_links"] is False
    assert body["text"].startswith("👀 *AI visibility · Acme*")


def test_discord_payload(config: Config) -> None:
    http = FakeHttp()
    DiscordSink("https://discord.test/x", http).send(alert(config))
    body = http.posts_to("discord")[0]
    assert body["allowed_mentions"] == {"parse": []}
    assert body["flags"] == 4


def test_webhook_payload(config: Config) -> None:
    http = FakeHttp()
    WebhookSink("https://hook.test/a", http).send(alert(config))
    body = http.posts_to("hook.test")[0]
    assert body["source"] == "ai-visibility-tracker"
    assert body["kind"] == "changes"
    assert body["answers"][0]["engine"] == "chatgpt"
    assert body["text"].startswith("👀 AI visibility · Acme")


def test_errors_do_not_leak_the_url(config: Config) -> None:
    http = FakeHttp(fail={"secret-path": 404})
    with pytest.raises(DeliveryError) as info:
        SlackSink("https://hooks.slack.test/secret-path", http).send(alert(config))
    assert "secret-path" not in str(info.value)
    assert "HTTP 404" in str(info.value)


def test_retry_on_503(config: Config) -> None:
    class Flaky(FakeHttp):
        def request(self, method, url, **kw):
            self.requests.append((method, url, kw))
            from conftest import FakeResponse

            return FakeResponse(503 if len(self.requests) == 1 else 200)

    http = Flaky()
    SlackSink("https://hooks.slack.test/x", http).send(alert(config))
    assert len(http.requests) == 2


def test_email(config: Config) -> None:
    settings = SmtpSettings.from_env(
        {"SMTP_HOST": "smtp.test", "EMAIL_TO": "a@x.test; b@x.test", "SMTP_USERNAME": "me@x.test"}
    )
    assert (settings.port, settings.security, settings.to) == (
        587,
        "starttls",
        ("a@x.test", "b@x.test"),
    )
    EmailSink(settings, FakeSMTP).send(alert(config))
    mail = FakeSMTP.sent[0]
    assert mail["Subject"] == "AI visibility · Acme: named in 1 of 1 answer (first check)"
    assert mail["From"] == "me@x.test"
    assert mail.get_body(("html",)) is not None
    with pytest.raises(DeliveryError, match="SMTP_SECURITY"):
        SmtpSettings.from_env({"SMTP_SECURITY": "tls", "EMAIL_FROM": "x@x.test"})


def test_sheet_id_and_account() -> None:
    url = "https://docs.google.com/spreadsheets/d/1AbC-d_9/edit#gid=0"
    assert sheet_id(url) == "1AbC-d_9"
    assert sheet_id(" 1AbC-d_9 ") == "1AbC-d_9"
    assert load_service_account(json.dumps(ACCOUNT))["client_email"] == "bot@proj.iam.test"
    with pytest.raises(DeliveryError, match="not valid JSON"):
        load_service_account("{nope")
    with pytest.raises(DeliveryError, match="needs client_email"):
        load_service_account('{"type": "service_account"}')
    with pytest.raises(DeliveryError, match="cannot read"):
        load_service_account("missing-file.json")


def test_sheet_row_formats_and_guards_formulas() -> None:
    row = sheet_row(CHECK, "best skates", "US")
    assert row == [
        "2026-11-17 07:00:21",
        "2026-11-17",
        "best skates",
        "US",
        "Google AI Mode",
        True,
        2,
        "Globex #1, Acme #2",
        "Globex",
        True,
        "forum.test, acme.test",
        "'-Acme is lighter",
        "first",
    ]
    assert len(row) == len(HEADER)


class Sheet(SheetSink):
    def assertion(self) -> str:  # no real key in tests
        return "signed.jwt.here"


def test_sheet_creates_tab_and_header_then_appends() -> None:
    http = FakeHttp()
    sink = Sheet("sheet1", ACCOUNT, http, tab="Answers", api_url="https://sheets.test")
    sink.append([sheet_row(CHECK, "best skates", "US")])
    sink.append([sheet_row(CHECK, "cheap skates", "US")])
    assert http.tabs["Answers"][0] == HEADER
    assert [r[2] for r in http.tabs["Answers"][1:]] == ["best skates", "cheap skates"]
    token_calls = [r for r in http.requests if r[1].endswith("/token")]
    assert len(token_calls) == 1  # the token is reused
    assert token_calls[0][2]["data"]["assertion"] == "signed.jwt.here"
    appends = [r for r in http.requests if r[1].endswith(":append")]
    assert appends[0][2]["params"]["valueInputOption"] == "USER_ENTERED"
    assert appends[0][2]["headers"]["Authorization"] == "Bearer tok"
    assert "'Answers'!A1" in appends[0][1].replace("%27", "'").replace("%21", "!")


def test_sheet_existing_tab_keeps_its_header() -> None:
    http = FakeHttp(tabs={"Answers": [["my", "own", "header"]]})
    sink = Sheet("sheet1", ACCOUNT, http, api_url="https://sheets.test")
    assert "ready" in sink.test()
    assert http.tabs["Answers"] == [["my", "own", "header"]]
    assert not any(":batchUpdate" in r[1] for r in http.requests)


def test_sheet_errors() -> None:
    http = FakeHttp(fail={":append": 403})
    sink = Sheet("sheet1", ACCOUNT, http, api_url="https://sheets.test")
    with pytest.raises(DeliveryError, match="sheet: HTTP 403"):
        sink.append([sheet_row(CHECK, "x", "US")])


def test_sheet_jwt_is_signed_with_the_account_key() -> None:
    rsa = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.rsa")
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    account = {**ACCOUNT, "private_key": pem, "private_key_id": "k1"}
    sink = SheetSink("s", account, FakeHttp(), clock=lambda: 1_800_000_000)
    head, body, sig = sink.assertion().split(".")

    def b64(part: str) -> bytes:
        return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))

    key.public_key().verify(
        b64(sig), f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256()
    )
    claims = json.loads(b64(body))
    assert claims == {
        "iss": "bot@proj.iam.test",
        "scope": "https://www.googleapis.com/auth/spreadsheets",
        "aud": "https://t/token",
        "iat": 1_800_000_000,
        "exp": 1_800_003_600,
    }


def test_build_destinations(config: Config) -> None:
    env = {**ENV, "SMTP_HOST": "smtp.test", "EMAIL_TO": "me@x.test", "EMAIL_FROM": "t@x.test"}
    dests = build_destinations(config, env, FakeHttp())
    assert [s.name for s in dests.alerts] == ["slack", "discord", "webhook"]
    assert [s.name for s in dests.digest] == ["slack", "email"]
    assert dests.alerts[0] is dests.digest[0]
    assert dests.sheet is None
    assert dests.skipped == ["sheet"]

    env.update(
        GOOGLE_SHEET_ID="abc",
        GOOGLE_SERVICE_ACCOUNT_JSON=json.dumps(ACCOUNT),
        GOOGLE_SHEETS_API_URL="http://127.0.0.1:1",
    )
    dests = build_destinations(config, env, FakeHttp())
    assert dests.sheet is not None and dests.sheet.api_url == "http://127.0.0.1:1"
    assert dests.skipped == []
    assert [s.name for s in dests.all] == ["sheet", "slack", "discord", "webhook", "email"]
