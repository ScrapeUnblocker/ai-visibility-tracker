"""The state file, ``state/visibility.json`` by default.

It holds every check of the last ``checks.history_days`` days (one line each, so the
committed file diffs well), the told state per prompt and engine (``baseline``: what the
last message said) and the week of the last digest. The workflow commits it back to the
repo, so it survives between scheduled runs.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .config import Config
from .process import Check, Seen

VERSION = 1


class StateError(RuntimeError):
    """The state file can't be read, or belongs to another brand."""


def pair_key(prompt_id: str, engine: str) -> str:
    return f"{prompt_id}:{engine}"


@dataclass
class State:
    brand: str = ""
    prompts: dict[str, dict[str, str]] = field(default_factory=dict)
    baseline: dict[str, Seen] = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)
    digest_week: str = ""

    # -- reading ------------------------------------------------------------------------

    @classmethod
    def load(cls, path: Path, brand: str = "") -> State:
        if not path.exists():
            return cls(brand=brand)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            state = cls(
                brand=str(raw.get("brand") or ""),
                prompts={str(k): dict(v) for k, v in (raw.get("prompts") or {}).items()},
                baseline={
                    str(k): Seen.from_dict(v) for k, v in (raw.get("baseline") or {}).items()
                },
                checks=[Check.from_dict(c) for c in raw.get("checks") or []],
                digest_week=str(raw.get("digest_week") or ""),
            )
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise StateError(f"cannot read {path}: {exc}") from None
        if brand and state.brand and state.brand != brand:
            raise StateError(
                f"{path} tracks {state.brand!r}, but config.yml now names {brand!r}. Delete the "
                "file (or set `state:` to a new path) to start fresh for the new brand."
            )
        state.brand = brand or state.brand
        return state

    def round_of(self, prompt_id: str, engine: str) -> list[Check]:
        """The checks of the latest round for a prompt on an engine (one, or two with the
        recheck), first answer first."""
        mine = [c for c in self.checks if c.prompt == prompt_id and c.engine == engine]
        if not mine:
            return []
        latest = max(c.round for c in mine)
        return sorted((c for c in mine if c.round == latest), key=lambda c: c.sample)

    def checked_on(self, prompt_id: str, engine: str, day: str) -> bool:
        return any(
            c.prompt == prompt_id and c.engine == engine and c.day == day for c in self.checks
        )

    def first_day(self) -> str:
        return min((c.day for c in self.checks), default="")

    # -- changing -----------------------------------------------------------------------

    def remember_prompts(self, config: Config) -> None:
        for p in config.prompts:
            self.prompts[p.id] = {"text": p.text, "country": p.country}

    def add(self, checks: list[Check]) -> None:
        # Oldest round first; within a round, in the order asked (config order).
        self.checks.extend(checks)
        self.checks.sort(key=lambda c: c.round)

    def prune(self, today: date, keep_days: int, config: Config) -> None:
        """Forget checks older than ``keep_days`` and prompts no longer in config.yml that
        have no checks left."""
        cutoff = (today - timedelta(days=keep_days)).isoformat()
        self.checks = [c for c in self.checks if c.day >= cutoff]
        live = {p.id for p in config.prompts} | {c.prompt for c in self.checks}
        self.prompts = {k: v for k, v in self.prompts.items() if k in live}
        self.baseline = {k: v for k, v in self.baseline.items() if k.split(":", 1)[0] in live}

    # -- writing ------------------------------------------------------------------------

    def dumps(self) -> str:
        head = {
            "version": VERSION,
            "brand": self.brand,
            "digest_week": self.digest_week or None,
            "prompts": dict(sorted(self.prompts.items())),
            "baseline": {k: self.baseline[k].to_dict() for k in sorted(self.baseline)},
        }
        lines = json.dumps(head, indent=1, ensure_ascii=False)[:-2]  # drop the closing "\n}"
        body = ",\n".join(
            "  " + json.dumps(c.to_dict(), ensure_ascii=False, separators=(",", ":"))
            for c in self.checks
        )
        checks = f',\n "checks": [\n{body}\n ]' if body else ',\n "checks": []'
        return f"{lines}{checks}\n}}\n"

    def save(self, path: Path) -> bool:
        """Write the file when its content changed. Returns True when it was written."""
        text = self.dumps()
        try:
            if path.exists() and path.read_text(encoding="utf-8") == text:
                return False
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            os.replace(tmp, path)
        except OSError as exc:
            raise StateError(f"cannot write {path}: {exc}") from None
        return True


def iso_week(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def as_dict(state: State) -> dict[str, Any]:
    return json.loads(state.dumps())
