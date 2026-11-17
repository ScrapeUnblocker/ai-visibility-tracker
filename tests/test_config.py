from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import CONFIG

from ai_visibility_tracker.config import (
    ConfigError,
    Prompt,
    clean_domain,
    load_config,
    parse_config,
)

REPO = Path(__file__).resolve().parents[1]


def minimal(**extra):
    raw = {"brand": {"name": "Acme"}, "prompts": ["best skates"]}
    raw.update(extra)
    return raw


def test_shipped_config_loads() -> None:
    config = load_config(REPO / "config.yml")
    assert config.brand.name == "Linear"
    assert config.brand.match_case is True
    assert [c.name for c in config.competitors][:2] == ["Jira", "GitHub Projects"]
    assert len(config.prompts) == 3
    assert config.engines == ("chatgpt", "gemini", "google_ai_mode")
    assert all(p.country == "US" for p in config.prompts)
    assert config.state == REPO / "state" / "visibility.json"


def test_test_config(write_config: Callable[..., Path]) -> None:
    config = load_config(write_config())
    assert config.brand.aliases == ("Acme Cloud",)
    assert config.brand.domains == ("acme.test",)
    assert config.digest.weekday == 0
    assert config.alerts.to == ("slack", "discord", "webhook")
    assert config.sheet.tab == "Answers"


def test_defaults() -> None:
    config = parse_config(minimal())
    assert config.competitors == ()
    assert config.country == "US"
    assert config.checks.recheck is True
    assert config.checks.history_days == 120
    assert config.digest.day == "monday"
    assert config.sheet.enabled is True
    assert config.state == Path("state/visibility.json")


def test_brand_as_plain_name_and_dedupe() -> None:
    config = parse_config(
        minimal(
            brand={
                "name": "Acme",
                "aliases": ["acme", "Acme Inc"],
                "domains": ["https://www.Acme.test/x"],
            },
            competitors=["Globex"],
        )
    )
    assert config.brand.aliases == ("Acme Inc",)
    assert config.brand.domains == ("acme.test",)
    assert config.competitors[0].name == "Globex"


def test_prompt_country_override_and_id() -> None:
    config = parse_config(
        minimal(prompts=["best skates", {"prompt": "beste Skates", "country": "de"}], country="gb")
    )
    assert [p.country for p in config.prompts] == ["GB", "DE"]
    assert Prompt("Best  Skates", "GB").id == config.prompts[0].id
    assert Prompt("best skates", "US").id != config.prompts[0].id


def test_find_prompts() -> None:
    config = parse_config(minimal(prompts=["best skates", "cheap skates"]))
    assert [p.text for p in config.find_prompts("CHEAP")] == ["cheap skates"]
    assert len(config.find_prompts("skates")) == 2


def test_clean_domain() -> None:
    assert clean_domain("https://www.Example.com:443/pricing?a=1") == "example.com"
    assert clean_domain("sub.example.co.uk/") == "sub.example.co.uk"


@pytest.mark.parametrize(
    "raw, message",
    [
        ({"prompts": ["x"]}, "brand: required"),
        (minimal(nope=1), "unknown setting(s) nope"),
        (minimal(prompts=[]), "prompts: expected a list"),
        (minimal(prompts=["a", "A "]), "listed twice"),
        (minimal(prompts=["x" * 2001]), "at most 2000"),
        (minimal(engines=["bing"]), "engines: expected"),
        (minimal(country="USA"), "2-letter country"),
        (minimal(language="english"), "language"),
        (minimal(brand={"name": "Acme", "domains": ["not a domain"]}), "expected a domain"),
        (minimal(competitors=[{"name": "acme"}]), "already a name"),
        (minimal(digest={"day": "someday"}), "digest.day"),
        (minimal(alerts={"to": ["pager"]}), "unknown destination"),
        (minimal(sheet={"tab": "a/b"}), "sheet.tab"),
        (minimal(checks={"history_days": 3}), "checks.history_days"),
        (minimal(checks={"recheck": "yes"}), "true or false"),
    ],
)
def test_errors(raw: dict, message: str) -> None:
    with pytest.raises(ConfigError, match=message.replace("(", r"\(").replace(")", r"\)")):
        parse_config(raw)


def test_digest_off() -> None:
    assert parse_config(minimal(digest={"day": "off"})).digest.weekday is None
    assert parse_config(minimal(digest={"day": False})).digest.weekday is None


def test_missing_and_invalid_file(tmp_path: Path, write_config: Callable[..., Path]) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yml")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_config(write_config("brand: [unclosed"))
    assert load_config(write_config(CONFIG)).brand.name == "Acme"
