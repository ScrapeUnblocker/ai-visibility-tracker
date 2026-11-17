from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from ai_visibility_tracker.config import Config
from ai_visibility_tracker.process import Check, Seen
from ai_visibility_tracker.state import State, StateError, iso_week, pair_key


def check(day: str, sample: int = 1, prompt: str = "p1", engine: str = "chatgpt") -> Check:
    return Check(
        round=f"{day}T07:00:00+00:00",
        at=f"{day}T07:00:{10 * sample}+00:00",
        day=day,
        prompt=prompt,
        engine=engine,
        sample=sample,
        named=True,
        rank=1,
        brands={"Acme": 1},
        ahead=[],
        cited=False,
        sites=["a.test"],
        excerpt="Acme — “quoted”",
    )


def test_round_trip_and_one_line_per_check(tmp_path: Path) -> None:
    path = tmp_path / "state" / "visibility.json"
    state = State(brand="Acme")
    state.prompts["p1"] = {"text": "best skates", "country": "US"}
    state.baseline[pair_key("p1", "chatgpt")] = Seen("2026-11-16", True, 1, [], False)
    state.add([check("2026-11-16"), check("2026-11-17"), check("2026-11-17", 2)])
    state.digest_week = "2026-W47"
    assert state.save(path)
    text = path.read_text(encoding="utf-8")
    raw = json.loads(text)
    assert raw["version"] == 1
    assert len(raw["checks"]) == 3
    assert sum(1 for line in text.splitlines() if line.startswith('  {"round"')) == 3
    assert "“quoted”" in text  # kept readable, not \u-escaped

    again = State.load(path, brand="Acme")
    assert again.checks == state.checks
    assert again.baseline == state.baseline
    assert again.digest_week == "2026-W47"
    assert not again.save(path)  # unchanged: not rewritten


def test_round_of_and_checked_on() -> None:
    state = State(brand="Acme")
    state.add([check("2026-11-16"), check("2026-11-17", 2), check("2026-11-17")])
    latest = state.round_of("p1", "chatgpt")
    assert [(c.day, c.sample) for c in latest] == [("2026-11-17", 1), ("2026-11-17", 2)]
    assert state.round_of("p1", "gemini") == []
    assert state.checked_on("p1", "chatgpt", "2026-11-16")
    assert not state.checked_on("p1", "gemini", "2026-11-16")
    assert state.first_day() == "2026-11-16"


def test_prune(config: Config) -> None:
    state = State(brand="Acme")
    gone = config.prompts[0].id
    state.prompts = {gone: {"text": "x", "country": "US"}, "old": {"text": "y", "country": ""}}
    state.baseline = {
        f"{gone}:chatgpt": Seen("2026-01-01", True, 1),
        "old:chatgpt": Seen("", False, None),
    }
    state.add([check("2026-07-01", prompt="old"), check("2026-11-17", prompt=gone)])
    state.prune(date(2026, 11, 17), 120, config)
    assert [c.prompt for c in state.checks] == [gone]
    assert set(state.prompts) == {gone}
    assert set(state.baseline) == {f"{gone}:chatgpt"}


def test_brand_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "v.json"
    State(brand="Acme").save(path)
    with pytest.raises(StateError, match="tracks 'Acme'"):
        State.load(path, brand="Globex")


def test_broken_file(tmp_path: Path) -> None:
    path = tmp_path / "v.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(StateError, match="cannot read"):
        State.load(path)


def test_iso_week() -> None:
    assert iso_week(date(2026, 11, 17)) == "2026-W47"
    assert iso_week(date(2027, 1, 1)) == "2026-W53"
