"""Shared fakes: an AI answers client, an HTTP client for the sinks (webhooks, the Google
token endpoint and the Sheets API), an SMTP server, and config files.

No test calls the real API, posts anywhere or sends email. The JSON below has the shape of
real answers from the ChatGPT, Gemini and Google AI Mode endpoints, with made-up brands.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest

from ai_visibility_tracker.config import Config, load_config

NOW = datetime(2026, 11, 17, 7, 0, tzinfo=UTC)  # a Tuesday

CONFIG = """
brand:
  name: Acme
  aliases: [Acme Cloud]
  domains: [acme.test]
competitors:
  - name: Globex
    domains: [globex.test]
  - name: Initech
  - name: Umbrella
    match_case: true
prompts:
  - best rocket skates for beginners
  - Globex alternatives for small teams
engines: [chatgpt, gemini, google_ai_mode]
country: US
language: en
checks:
  recheck: true
  history_days: 120
alerts:
  to: [slack, discord, webhook]
digest:
  day: monday
  to: [slack, email]
sheet:
  enabled: true
  tab: Answers
state: state/visibility.json
"""

GOOD = """For beginners, my top pick is **Acme**.

![Skate park](https://img.test/park.png)

1. Acme Cloud Skates - smooth and safe
2. Globex Glide - cheaper
3. [Initech Roll](https://initech.test/roll) - for kids
"""

BEHIND = """Most people start with Globex.

1. Globex Glide - the classic
2. Acme Skates - lighter, see [acme.test](https://acme.test/skates)
"""

MISSING = """Popular picks are Globex and Initech. An umbrella helps on rainy days."""


def chatgpt_json(markdown: str, domains: list[str] | None = None) -> dict[str, Any]:
    domains = domains or []
    return {
        "url": "https://chatgpt.com/",
        "country": "US",
        "prompt": "q",
        "answer": markdown.replace("**", ""),
        "answerMarkdown": markdown,
        "citations": [
            {"position": 1, "siteName": "Reviews", "domain": "reviews.test", "moreSources": 2}
        ],
        "links": [
            {"position": i, "title": d, "url": f"https://www.{d}/", "domain": d}
            for i, d in enumerate(domains, 1)
        ],
        "sources": [{"position": 1, "siteName": "Reviews", "domain": "reviews.test"}]
        + [{"position": i, "siteName": None, "domain": d} for i, d in enumerate(domains, 2)],
        "webSearch": True,
        "model": None,
        "conversationId": "c1",
    }


def gemini_json(markdown: str, urls: list[str] | None = None) -> dict[str, Any]:
    urls = urls or []
    return {
        "url": "https://gemini.google.com/app",
        "country": "US",
        "proxyCountry": "US",
        "prompt": "q",
        "answer": markdown,
        "answerMarkdown": markdown,
        "citations": [
            {"position": i, "title": "t", "url": u, "domain": u.split("/")[2]}
            for i, u in enumerate(urls, 1)
        ],
        "sources": [],
        "webSearch": bool(urls),
        "followUpPrompts": [],
        "richBlocks": 0,
        "model": "Flash",
        "location": "Boston, USA",
        "locationCountry": "US",
        "complete": True,
        "conversationId": "c_2",
    }


def ai_mode_json(markdown: str, links: list[str] | None = None) -> dict[str, Any]:
    return {
        "query": "q",
        "hl": "en",
        "gl": "us",
        "proxyCountry": "US",
        "url": "https://www.google.com/search?q=q&udm=50",
        "answer": {"text": markdown, "markdown": markdown, "blocks": []},
        "followUps": [],
        "references": [
            {
                "title": "Forum",
                "url": "https://www.forum.test/t/1",
                "source": "Forum",
                "domain": "forum.test",
                "snippet": "...",
                "position": 1,
            }
        ],
        "links": [{"text": "x", "url": u} for u in links or []],
    }


SHAPES = {"chatgpt": chatgpt_json, "gemini": gemini_json, "google_ai_mode": ai_mode_json}


class FakeClient:
    """Stands in for ``scrapeunblocker.Client``. ``answers`` maps an engine to a list of
    responses (dicts or exceptions), consumed in order; the last one repeats. A dict can
    also map prompt text to such a list."""

    def __init__(self, answers: dict[str, Any] | None = None):
        self.answers = answers or {}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def _next(self, engine: str, prompt: str) -> Any:
        queue = self.answers.get(engine)
        if isinstance(queue, dict):
            queue = queue.get(prompt)
        if not queue:
            raise AssertionError(f"unexpected {engine} call for {prompt!r}")
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def chatgpt(self, prompt: str, *, country: str | None = None) -> Any:
        self.calls.append(("chatgpt", prompt, {"country": country}))
        return self._next("chatgpt", prompt)

    def gemini(self, prompt: str, *, country: str | None = None) -> Any:
        self.calls.append(("gemini", prompt, {"country": country}))
        return self._next("gemini", prompt)

    def google_ai_mode(self, q: str, **kwargs: Any) -> Any:
        self.calls.append(("google_ai_mode", q, kwargs))
        return self._next("google_ai_mode", q)


def same_answers(markdown: str = GOOD, domains: list[str] | None = None) -> FakeClient:
    """Every engine gives the same kind of answer."""
    domains = ["acme.test"] if domains is None else domains
    return FakeClient(
        {
            "chatgpt": [chatgpt_json(markdown, domains)],
            "gemini": [gemini_json(markdown, [f"https://{d}/p" for d in domains])],
            "google_ai_mode": [ai_mode_json(markdown, [f"https://{d}/" for d in domains])],
        }
    )


class FakeResponse:
    def __init__(self, status_code: int = 200, body: Any = "ok", headers: Any = None):
        self.status_code = status_code
        self._body = body
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.headers = headers or {}

    def json(self) -> Any:
        if isinstance(self._body, str):
            return json.loads(self._body)
        return self._body


class FakeHttp:
    """Records every request. Plays the Google token endpoint and a small Sheets API
    (tabs in ``self.tabs``). ``fail`` maps a URL substring to a status code."""

    def __init__(self, fail: dict[str, int] | None = None, tabs: dict[str, list] | None = None):
        self.requests: list[tuple[str, str, dict[str, Any]]] = []
        self.fail = fail or {}
        self.tabs: dict[str, list[list[Any]]] = tabs if tabs is not None else {"Sheet1": []}

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append((method, url, kwargs))
        for part, status in self.fail.items():
            if part in url:
                return FakeResponse(status, "boom")
        if url.endswith("/token"):
            return FakeResponse(200, {"access_token": "tok", "expires_in": 3600})
        if "/v4/spreadsheets/" in url:
            return self._sheets(method, unquote(url), kwargs)
        return FakeResponse()

    def _sheets(self, method: str, url: str, kwargs: dict[str, Any]) -> FakeResponse:
        tail = url.split("/v4/spreadsheets/", 1)[1]
        sid, _, rest = tail.partition("/")
        if sid.endswith(":batchUpdate"):
            for r in kwargs["json"]["requests"]:
                self.tabs.setdefault(r["addSheet"]["properties"]["title"], [])
            return FakeResponse(200, {})
        if not rest:
            return FakeResponse(200, {"sheets": [{"properties": {"title": t}} for t in self.tabs]})
        rng = rest.removeprefix("values/").removesuffix(":append")
        tab = rng.split("!")[0].strip("'")
        rows = self.tabs[tab]
        if method == "GET":
            return FakeResponse(200, {"values": rows[:1]} if rows else {})
        if method == "PUT":
            rows[0:1] = kwargs["json"]["values"]
        else:
            rows.extend(kwargs["json"]["values"])
        return FakeResponse(200, {})

    def close(self) -> None:
        pass

    def posts_to(self, part: str) -> list[Any]:
        return [k.get("json") for m, u, k in self.requests if m == "POST" and part in u]

    @property
    def chat_posts(self) -> list[tuple[str, Any]]:
        return [
            (u, k.get("json"))
            for m, u, k in self.requests
            if m == "POST" and "/v4/" not in u and not u.endswith("/token")
        ]


class FakeSMTP:
    """Records sent emails; used as the context manager ``EmailSink`` opens."""

    sent: list[Any] = []

    def __init__(self, settings: Any) -> None:
        self.settings = settings

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def send_message(self, mail: Any) -> None:
        FakeSMTP.sent.append(mail)


ENV = {
    "SCRAPEUNBLOCKER_KEY": "test-key",
    "SLACK_WEBHOOK_URL": "https://hooks.slack.test/services/x",
    "DISCORD_WEBHOOK_URL": "https://discord.test/api/webhooks/x",
    "ALERT_WEBHOOK_URL": "https://hook.test/alerts",
}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _s: None)


@pytest.fixture(autouse=True)
def reset_smtp() -> None:
    FakeSMTP.sent = []


@pytest.fixture
def write_config(tmp_path: Path) -> Callable[..., Path]:
    def write(text: str = CONFIG, extra: str = "") -> Path:
        path = tmp_path / "config.yml"
        path.write_text(text + extra, encoding="utf-8")
        return path

    return write


@pytest.fixture
def config(write_config: Callable[..., Path]) -> Config:
    return load_config(write_config())
