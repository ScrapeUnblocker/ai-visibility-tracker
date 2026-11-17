"""Load and check ``config.yml``, the one file a user edits.

Secrets never live here: the API key, webhook URLs, SMTP login and the Google service
account come from environment variables.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Engine id -> the name people know it by.
ENGINES = {"chatgpt": "ChatGPT", "gemini": "Gemini", "google_ai_mode": "Google AI Mode"}
DESTINATIONS = ("slack", "discord", "email", "webhook")
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
MAX_PROMPT = 2000  # ChatGPT's limit; Gemini takes 4000
MAX_COMPETITORS = 20

_COUNTRY = re.compile(r"^[A-Za-z]{2}$")
_LANGUAGE = re.compile(r"^[a-z]{2,3}(-[A-Za-z]{2,4})?$")
_DOMAIN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
_TAB = re.compile(r"^[^\[\]*?/\\:]{1,100}$")


class ConfigError(ValueError):
    """config.yml is missing, unreadable or has a value that cannot work."""


def clean_domain(value: str) -> str:
    """``"https://www.Acme.com/pricing"`` -> ``"acme.com"``."""
    text = value.strip().lower()
    text = re.sub(r"^[a-z]+://", "", text)
    text = text.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    text = text.rsplit("@", 1)[-1].split(":", 1)[0].rstrip(".")
    return text.removeprefix("www.")


@dataclass(frozen=True)
class Brand:
    """A brand to look for in answers: yours or a competitor's."""

    name: str
    aliases: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    match_case: bool = False

    @property
    def names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


@dataclass(frozen=True)
class Prompt:
    """A question people ask an AI assistant, asked from ``country``."""

    text: str
    country: str = ""  # two letters, upper case; empty = any location

    @property
    def id(self) -> str:
        """Stable id in the state file. Editing the text or the country makes a new prompt."""
        key = f"{' '.join(self.text.casefold().split())}|{self.country}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


@dataclass(frozen=True)
class Checks:
    recheck: bool = True
    history_days: int = 120


@dataclass(frozen=True)
class Alerts:
    to: tuple[str, ...] = ("slack", "discord", "webhook")


@dataclass(frozen=True)
class Digest:
    day: str = "monday"  # or "off"
    to: tuple[str, ...] = DESTINATIONS

    @property
    def weekday(self) -> int | None:
        """0 = Monday, None = no weekly digest."""
        return None if self.day == "off" else DAYS.index(self.day)


@dataclass(frozen=True)
class Sheet:
    enabled: bool = True
    tab: str = "Answers"


@dataclass(frozen=True)
class Config:
    brand: Brand
    prompts: tuple[Prompt, ...]
    competitors: tuple[Brand, ...] = ()
    engines: tuple[str, ...] = tuple(ENGINES)
    country: str = "US"  # the default for prompts without their own
    language: str = "en"
    checks: Checks = field(default_factory=Checks)
    alerts: Alerts = field(default_factory=Alerts)
    digest: Digest = field(default_factory=Digest)
    sheet: Sheet = field(default_factory=Sheet)
    state: Path = Path("state/visibility.json")

    @property
    def brands(self) -> tuple[Brand, ...]:
        """Your brand first, then the competitors."""
        return (self.brand, *self.competitors)

    def find_prompts(self, text: str) -> list[Prompt]:
        wanted = " ".join(text.casefold().split())
        return [p for p in self.prompts if wanted in p.text.casefold() or wanted == p.id]


def _bool(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{where}: expected true or false, got {value!r}")
    return value


def _int(value: Any, where: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{where}: expected a whole number, got {value!r}")
    if not low <= value <= high:
        raise ConfigError(f"{where}: must be {low}-{high}, got {value}")
    return value


def _text(value: Any, where: str) -> str:
    if value is None:
        return ""
    if isinstance(value, int | float) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        raise ConfigError(f"{where}: expected text, got {value!r}")
    return " ".join(value.split())


def _list(value: Any, where: str) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        raise ConfigError(f"{where}: expected a list")
    return value


def _mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{key}: expected a section of settings")
    return value


def _unknown(section: dict[str, Any], allowed: set[str], where: str) -> None:
    extra = sorted(str(k) for k in set(section) - allowed)
    if extra:
        raise ConfigError(f"{where}: unknown setting(s) {', '.join(extra)}")


def _country(value: Any, where: str) -> str:
    text = _text(value, where)
    if text and not _COUNTRY.match(text):
        raise ConfigError(f"{where}: expected a 2-letter country code such as US, got {text!r}")
    return text.upper()


def _destinations(value: Any, where: str, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    items = _list(value, where)
    bad = [str(d) for d in items if d not in DESTINATIONS]
    if bad:
        raise ConfigError(
            f"{where}: unknown destination(s) {', '.join(bad)}; use {', '.join(DESTINATIONS)}"
        )
    return tuple(dict.fromkeys(items))


BRAND_KEYS = {"name", "aliases", "domains", "match_case"}


def parse_brand(raw: Any, where: str) -> Brand:
    if isinstance(raw, str):
        raw = {"name": raw}
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: expected a name or a mapping with name, aliases, domains")
    _unknown(raw, BRAND_KEYS, where)
    name = _text(raw.get("name"), f"{where}.name")
    if not name:
        raise ConfigError(f"{where}.name: the brand name is required")
    aliases: dict[str, str] = {name.casefold(): name}
    for i, item in enumerate(_list(raw.get("aliases"), f"{where}.aliases")):
        alias = _text(item, f"{where}.aliases[{i}]")
        if not alias:
            raise ConfigError(f"{where}.aliases[{i}]: empty entry")
        aliases.setdefault(alias.casefold(), alias)
    domains: list[str] = []
    for i, item in enumerate(_list(raw.get("domains"), f"{where}.domains")):
        text = _text(item, f"{where}.domains[{i}]")
        domain = clean_domain(text)
        if not _DOMAIN.match(domain):
            raise ConfigError(f"{where}.domains[{i}]: expected a domain such as acme.com: {text!r}")
        if domain not in domains:
            domains.append(domain)
    return Brand(
        name=name,
        aliases=tuple(list(aliases.values())[1:]),
        domains=tuple(domains),
        match_case=_bool(raw.get("match_case", False), f"{where}.match_case"),
    )


def parse_prompt(raw: Any, where: str, country: str) -> Prompt:
    if isinstance(raw, str):
        raw = {"prompt": raw}
    if not isinstance(raw, dict):
        raise ConfigError(
            f"{where}: expected the question as text, or {{prompt: ..., country: ..}}"
        )
    _unknown(raw, {"prompt", "country"}, where)
    text = _text(raw.get("prompt"), f"{where}.prompt")
    if not text:
        raise ConfigError(f"{where}: empty prompt")
    if len(text) > MAX_PROMPT:
        raise ConfigError(f"{where}: at most {MAX_PROMPT} characters, got {len(text)}")
    own = _country(raw.get("country"), f"{where}.country")
    return Prompt(text=text, country=own or country)


TOP_KEYS = {
    "brand",
    "competitors",
    "prompts",
    "engines",
    "country",
    "language",
    "checks",
    "alerts",
    "digest",
    "sheet",
    "state",
}


def parse_config(raw: Any, base_dir: Path | None = None) -> Config:
    if not isinstance(raw, dict):
        raise ConfigError("config.yml must be a mapping of settings")
    _unknown(raw, TOP_KEYS, "config.yml")

    if raw.get("brand") is None:
        raise ConfigError("brand: required, for example brand: {name: Acme, domains: [acme.com]}")
    brand = parse_brand(raw["brand"], "brand")
    competitors: list[Brand] = []
    seen = {n.casefold() for n in brand.names}
    comp_raw = _list(raw.get("competitors"), "competitors")
    if len(comp_raw) > MAX_COMPETITORS:
        raise ConfigError(f"competitors: at most {MAX_COMPETITORS}, got {len(comp_raw)}")
    for i, item in enumerate(comp_raw):
        comp = parse_brand(item, f"competitors[{i}]")
        clash = [n for n in comp.names if n.casefold() in seen]
        if clash:
            raise ConfigError(f"competitors[{i}]: {clash[0]!r} is already a name of another brand")
        seen.update(n.casefold() for n in comp.names)
        competitors.append(comp)

    country = _country(raw.get("country", "US"), "country")
    prompts_raw = raw.get("prompts")
    if not isinstance(prompts_raw, list) or not prompts_raw:
        raise ConfigError("prompts: expected a list of questions, e.g. - best CRM for a startup")
    prompts: list[Prompt] = []
    for i, item in enumerate(prompts_raw):
        prompt = parse_prompt(item, f"prompts[{i}]", country)
        if any(p.id == prompt.id for p in prompts):
            raise ConfigError(f"prompts[{i}]: {prompt.text!r} is listed twice")
        prompts.append(prompt)

    engines_raw = raw.get("engines", list(ENGINES))
    engines = _list(engines_raw, "engines")
    bad = [str(e) for e in engines if e not in ENGINES]
    if bad or not engines:
        raise ConfigError(f"engines: expected a list of {', '.join(ENGINES)}")

    language = _text(raw.get("language", "en"), "language") or "en"
    if not _LANGUAGE.match(language):
        raise ConfigError(f"language: expected a language code such as en or pt-BR: {language!r}")

    checks_raw = _mapping(raw, "checks")
    _unknown(checks_raw, {"recheck", "history_days"}, "checks")
    checks = Checks(
        recheck=_bool(checks_raw.get("recheck", True), "checks.recheck"),
        history_days=_int(checks_raw.get("history_days", 120), "checks.history_days", 14, 730),
    )

    alerts_raw = _mapping(raw, "alerts")
    _unknown(alerts_raw, {"to"}, "alerts")
    alerts = Alerts(to=_destinations(alerts_raw.get("to"), "alerts.to", Alerts.to))

    digest_raw = _mapping(raw, "digest")
    _unknown(digest_raw, {"day", "to"}, "digest")
    day_value = digest_raw.get("day", "monday")
    day = "off" if day_value is False else _text(day_value, "digest.day").lower()
    if day not in (*DAYS, "off"):
        raise ConfigError(f"digest.day: expected a weekday such as monday, or off, got {day!r}")
    digest = Digest(day=day, to=_destinations(digest_raw.get("to"), "digest.to", Digest.to))

    sheet_raw = _mapping(raw, "sheet")
    _unknown(sheet_raw, {"enabled", "tab"}, "sheet")
    tab = _text(sheet_raw.get("tab", "Answers"), "sheet.tab") or "Answers"
    if not _TAB.match(tab):
        raise ConfigError(f"sheet.tab: a sheet tab name can't contain [ ] * ? / \\ : ({tab!r})")
    sheet = Sheet(enabled=_bool(sheet_raw.get("enabled", True), "sheet.enabled"), tab=tab)

    return Config(
        brand=brand,
        prompts=tuple(prompts),
        competitors=tuple(competitors),
        engines=tuple(dict.fromkeys(engines)),
        country=country,
        language=language,
        checks=checks,
        alerts=alerts,
        digest=digest,
        sheet=sheet,
        state=_path(raw.get("state") or "state/visibility.json", "state", base_dir),
    )


def _path(value: Any, where: str, base_dir: Path | None) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where}: expected a path")
    path = Path(value.strip())
    if base_dir is not None and not path.is_absolute():
        path = base_dir / path
    return path


def load_config(path: str | Path) -> Config:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"{path} not found (run from the repo folder or pass --config)") from None
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from None
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from None
    return parse_config(raw, base_dir=path.resolve().parent)
