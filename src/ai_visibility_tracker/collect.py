"""Ask ChatGPT, Gemini and Google AI Mode through the ScrapeUnblocker API.

One SDK call per prompt and engine:

- ``client.chatgpt(prompt, country="US")`` (``POST /ai/chatgpt``): signed-out ChatGPT
- ``client.gemini(prompt, country="US")`` (``POST /ai/gemini``): signed-out Gemini
- ``client.google_ai_mode(prompt, proxy_country="US", hl="en")``
  (``POST /search/google-ai-mode``): the AI Mode tab of Google Search

Each returns the finished answer (Markdown) and the sites it cites or links. Every call
starts a new conversation, and answers vary between identical calls, as they do for people.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from scrapeunblocker import (
    AuthenticationError,
    BlockedError,
    BrowserTimeoutError,
    InvalidRequestError,
    PaymentRequiredError,
    RateLimitError,
    ScrapeTimeoutError,
    ScrapeUnblockerError,
    ServerError,
    UpstreamOutageError,
    ValidationError,
)
from scrapeunblocker import ConnectionError as SUConnectionError

from .config import ENGINES, clean_domain

log = logging.getLogger(__name__)

# Errors that end the whole run: asking the next prompt cannot help.
FATAL = (AuthenticationError, PaymentRequiredError)
# Errors worth one more try after a pause: a busy or slow assistant, a dropped connection.
RETRYABLE = (
    ServerError,
    RateLimitError,
    UpstreamOutageError,
    ScrapeTimeoutError,
    SUConnectionError,
    BlockedError,
    BrowserTimeoutError,
)
RETRY_PAUSE = 30.0


class AiClient(Protocol):
    def chatgpt(self, prompt: str, *, country: str | None = None) -> Any: ...

    def gemini(self, prompt: str, *, country: str | None = None) -> Any: ...

    def google_ai_mode(
        self,
        q: str,
        *,
        proxy_country: str | None = None,
        gl: str | None = None,
        hl: str | None = None,
    ) -> Any: ...


class AskError(RuntimeError):
    """An engine gave no answer this run.

    ``permanent`` means the prompt was refused (config.yml needs a fix). Otherwise the
    prompt is asked again on the next run. ``calls`` counts the API calls spent.
    """

    def __init__(self, message: str, *, permanent: bool = False, calls: int = 0):
        super().__init__(message)
        self.permanent = permanent
        self.calls = calls


@dataclass(frozen=True)
class Answer:
    engine: str
    prompt: str
    markdown: str  # the answer as the engine wrote it
    sites: tuple[str, ...] = ()  # domains cited or linked, in order of first appearance
    web_search: bool | None = None
    located: str = ""  # the country the engine placed the visitor in, when it says

    @property
    def label(self) -> str:
        return ENGINES[self.engine]


def _str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _domains(groups: Iterable[Any]) -> tuple[str, ...]:
    """Domains from lists of citation/link/source dicts (``domain`` or ``url``)."""
    out: list[str] = []
    for group in groups:
        if not isinstance(group, list):
            continue
        for item in group:
            if not isinstance(item, dict):
                continue
            raw = _str(item.get("domain")) or _str(item.get("url"))
            domain = clean_domain(raw) if raw else ""
            if domain and "." in domain and domain not in out:
                out.append(domain)
    return tuple(out)


def shape(engine: str, prompt: str, data: Any) -> Answer:
    """One engine's JSON answer -> :class:`Answer`. Raises :class:`AskError` when empty."""
    if not isinstance(data, dict):
        raise AskError(f"{ENGINES[engine]}: unexpected answer ({type(data).__name__})", calls=1)
    if engine == "google_ai_mode":
        answer = data.get("answer")
        answer = answer if isinstance(answer, dict) else {}
        markdown = _str(answer.get("markdown")) or _str(answer.get("text"))
        sites = _domains([data.get("references"), data.get("links")])
        web_search: bool | None = True
        located = _str(data.get("gl")).upper()
    else:
        markdown = _str(data.get("answerMarkdown")) or _str(data.get("answer"))
        sites = _domains([data.get("citations"), data.get("links"), data.get("sources")])
        web_search = data.get("webSearch") if isinstance(data.get("webSearch"), bool) else None
        located = _str(data.get("locationCountry") or data.get("country")).upper()
    if not markdown:
        raise AskError(f"{ENGINES[engine]} returned an empty answer", calls=1)
    return Answer(engine, prompt, markdown, sites, web_search, located)


def ask(
    client: AiClient,
    engine: str,
    prompt: str,
    *,
    country: str = "",
    language: str = "en",
    sleep: Callable[[float], None] | None = None,
) -> tuple[Answer, int]:
    """Ask one engine one prompt: one call, one retry after a temporary error.

    Returns the answer and the number of API calls spent.
    """
    label = ENGINES[engine]
    calls = 0
    for attempt in (1, 2):
        calls += 1
        try:
            log.info("%s %r country=%s", engine, prompt, country or "-")
            if engine == "chatgpt":
                data = client.chatgpt(prompt, country=country or None)
            elif engine == "gemini":
                data = client.gemini(prompt, country=country or None)
            else:
                data = client.google_ai_mode(prompt, proxy_country=country or None, hl=language)
        except FATAL:
            raise
        except (InvalidRequestError, ValidationError) as exc:
            raise AskError(
                f"{label} refused the prompt: {exc}", permanent=True, calls=calls
            ) from None
        except RETRYABLE as exc:
            if attempt == 1:
                log.info("retrying %s after %s", engine, type(exc).__name__)
                (sleep or time.sleep)(RETRY_PAUSE)
                continue
            raise AskError(
                f"{label} gave no answer ({type(exc).__name__}: {exc}). Asked again next run.",
                calls=calls,
            ) from None
        except ScrapeUnblockerError as exc:
            raise AskError(f"{label}: {type(exc).__name__}: {exc}", calls=calls) from None
        try:
            return shape(engine, prompt, data), calls
        except AskError as exc:
            if attempt == 1:
                (sleep or time.sleep)(RETRY_PAUSE)
                continue
            exc.calls = calls
            raise
    raise AssertionError("unreachable")
