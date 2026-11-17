from __future__ import annotations

import pytest
from conftest import GOOD, FakeClient, ai_mode_json, chatgpt_json, gemini_json
from scrapeunblocker import (
    AuthenticationError,
    InvalidRequestError,
    ScrapeTimeoutError,
    ServerError,
    UpstreamOutageError,
)

from ai_visibility_tracker.collect import AskError, ask, shape


def test_shape_chatgpt() -> None:
    answer = shape("chatgpt", "q", chatgpt_json(GOOD, ["acme.test", "www.globex.test"]))
    assert answer.markdown.startswith("For beginners")
    assert answer.sites == ("reviews.test", "acme.test", "globex.test")
    assert answer.web_search is True
    assert answer.located == "US"
    assert answer.label == "ChatGPT"


def test_shape_gemini() -> None:
    answer = shape("gemini", "q", gemini_json(GOOD, ["https://www.acme.test/a"]))
    assert answer.sites == ("acme.test",)


def test_shape_ai_mode_uses_link_urls() -> None:
    answer = shape("google_ai_mode", "q", ai_mode_json(GOOD, ["https://acme.test/x"]))
    assert answer.sites == ("forum.test", "acme.test")
    assert answer.located == "US"


def test_shape_empty_answer() -> None:
    with pytest.raises(AskError, match="empty answer"):
        shape("gemini", "q", gemini_json(""))
    with pytest.raises(AskError, match="unexpected answer"):
        shape("chatgpt", "q", ["not", "a", "dict"])


def test_ask_passes_country_and_language() -> None:
    client = FakeClient({"google_ai_mode": [ai_mode_json(GOOD)], "chatgpt": [chatgpt_json(GOOD)]})
    ask(client, "google_ai_mode", "best skates", country="GB", language="en-GB")
    ask(client, "chatgpt", "best skates", country="")
    assert client.calls[0][2] == {"proxy_country": "GB", "hl": "en-GB"}
    assert client.calls[1][2] == {"country": None}


def test_ask_retries_once() -> None:
    client = FakeClient(
        {"chatgpt": [UpstreamOutageError("busy", status_code=503), chatgpt_json(GOOD)]}
    )
    answer, calls = ask(client, "chatgpt", "q")
    assert calls == 2
    assert answer.engine == "chatgpt"


def test_ask_gives_up_after_two() -> None:
    client = FakeClient({"gemini": [ServerError("no answer", status_code=502)]})
    with pytest.raises(AskError) as info:
        ask(client, "gemini", "q")
    assert info.value.calls == 2
    assert not info.value.permanent
    assert "Asked again next run" in str(info.value)


def test_ask_timeout_then_empty() -> None:
    client = FakeClient({"gemini": [ScrapeTimeoutError("slow"), gemini_json("")]})
    with pytest.raises(AskError, match="empty answer") as info:
        ask(client, "gemini", "q")
    assert info.value.calls == 2


def test_ask_refused_prompt_is_permanent() -> None:
    client = FakeClient({"chatgpt": [InvalidRequestError("too long", status_code=400)]})
    with pytest.raises(AskError) as info:
        ask(client, "chatgpt", "q")
    assert info.value.permanent
    assert info.value.calls == 1


def test_ask_auth_error_ends_the_run() -> None:
    client = FakeClient({"chatgpt": [AuthenticationError("bad key", status_code=401)]})
    with pytest.raises(AuthenticationError):
        ask(client, "chatgpt", "q")
