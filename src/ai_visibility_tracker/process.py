"""Read an answer for your brand, and decide what changed.

- :func:`read_answer` turns one answer into a :class:`Check`: is your brand named, at which
  rank among the brands you track (the order they are first named in), who is named before
  you, and is your site among the cited or linked sites.
- :func:`changes` compares a check with the last state you were told about.
- :func:`confirmed` keeps a change only when every answer of the round agrees (the second
  answer is the recheck), and :func:`advance` moves the told state forward.
- :func:`weekly` sums up seven days of checks for the digest.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any

from .collect import Answer
from .config import Brand, Config, Prompt

EXCERPT = 160
MAX_SITES = 15

_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\((?:[^()\s]|\([^)]*\))*\)")
_URL = re.compile(r"https?://\S+")
_LEAD = re.compile(r"^\s*(?:[>#*+\-|]+\s*|\d+[.)]\s+)*")  # quote, heading, list, table
_EMPHASIS = re.compile(r"[*`]+")
_PIPE = re.compile(r"\s*\|\s*")


def plain_line(line: str) -> str:
    """One Markdown line as plain text: ``"2. **Acme** | fast"`` -> ``"Acme fast"``."""
    line = _PIPE.sub(" ", _EMPHASIS.sub("", _LEAD.sub("", line)))
    return " ".join(line.split())


def visible_text(markdown: str) -> str:
    """The answer as a reader sees it: images, link targets and bare URLs removed."""
    text = _IMAGE.sub(" ", markdown)
    text = _LINK.sub(r"\1", text)
    return _URL.sub(" ", text)


def matcher(brand: Brand) -> re.Pattern[str]:
    """Whole-word match of the brand's names. ``Acme`` matches "Acme's", not "Acmeville"."""
    names = sorted(brand.names, key=len, reverse=True)
    body = "|".join(re.escape(n) for n in names)
    flags = 0 if brand.match_case else re.IGNORECASE
    return re.compile(rf"(?<!\w)(?:{body})(?!\w)", flags)


def first_mentions(text: str, brands: Iterable[Brand]) -> dict[str, int]:
    """Brand name -> character offset of its first mention, for brands that are named."""
    found: dict[str, int] = {}
    for brand in brands:
        m = matcher(brand).search(text)
        if m:
            found[brand.name] = m.start()
    return found


def excerpt(text: str, offset: int, width: int = EXCERPT) -> str:
    """The line holding ``offset``, without Markdown markup, at most ``width`` characters."""
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    raw = text[start : end if end != -1 else len(text)]
    line = plain_line(raw)
    if len(line) <= width:
        return line
    # Keep the mention in view on long lines.
    pos = max(0, len(plain_line(raw[: offset - start])) - width // 3)
    cut = line[pos : pos + width - 2].strip()
    return ("…" if pos else "") + cut + "…"


def owns(domain: str, domains: Iterable[str]) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in domains)


@dataclass
class Check:
    """One answer, read for your brand. ``sample`` 2 is the recheck of the same round."""

    round: str  # ISO time of the round's first answer
    day: str  # UTC date, YYYY-MM-DD
    prompt: str  # Prompt.id
    engine: str
    sample: int
    named: bool
    rank: int | None  # your place among the tracked brands named, 1 = named first
    brands: dict[str, int]  # tracked brand -> rank, for each one named
    ahead: list[str]  # competitors named before you
    cited: bool  # your site is cited or linked
    sites: list[str]  # cited or linked domains, first MAX_SITES
    excerpt: str  # the line that first names you
    at: str = ""  # ISO time of this answer
    sheet: bool = False  # written to the Google Sheet

    def to_dict(self) -> dict[str, Any]:
        return {
            "round": self.round,
            "at": self.at or self.round,
            "day": self.day,
            "prompt": self.prompt,
            "engine": self.engine,
            "sample": self.sample,
            "named": self.named,
            "rank": self.rank,
            "brands": self.brands,
            "ahead": self.ahead,
            "cited": self.cited,
            "sites": self.sites,
            "excerpt": self.excerpt,
            "sheet": self.sheet,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Check:
        return cls(
            round=str(raw["round"]),
            at=str(raw.get("at") or raw["round"]),
            day=str(raw["day"]),
            prompt=str(raw["prompt"]),
            engine=str(raw["engine"]),
            sample=int(raw.get("sample", 1)),
            named=bool(raw["named"]),
            rank=raw.get("rank"),
            brands={str(k): int(v) for k, v in (raw.get("brands") or {}).items()},
            ahead=[str(x) for x in raw.get("ahead") or []],
            cited=bool(raw.get("cited")),
            sites=[str(x) for x in raw.get("sites") or []],
            excerpt=str(raw.get("excerpt") or ""),
            sheet=bool(raw.get("sheet")),
        )


def tracked_for(config: Config, prompt: Prompt) -> list[Brand]:
    """The brands to look for in answers to ``prompt``. A competitor the prompt itself names
    ("Jira alternatives") is left out: every answer repeats it, usually first."""
    return [config.brand] + [b for b in config.competitors if not matcher(b).search(prompt.text)]


def read_answer(
    answer: Answer,
    config: Config,
    prompt: Prompt,
    *,
    round_at: str,
    at: str,
    sample: int = 1,
) -> Check:
    text = visible_text(answer.markdown)
    offsets = first_mentions(text, tracked_for(config, prompt))
    order = sorted(offsets, key=lambda name: offsets[name])
    ranks = {name: i for i, name in enumerate(order, 1)}
    me = config.brand.name
    rank = ranks.get(me)
    ahead = [name for name in order if rank is not None and ranks[name] < rank]
    return Check(
        round=round_at,
        at=at,
        day=round_at[:10],
        prompt=prompt.id,
        engine=answer.engine,
        sample=sample,
        named=rank is not None,
        rank=rank,
        brands=ranks,
        ahead=ahead,
        cited=any(owns(d, config.brand.domains) for d in answer.sites),
        sites=list(answer.sites[:MAX_SITES]),
        excerpt=excerpt(text, offsets[me]) if me in offsets else "",
    )


# -- what changed -------------------------------------------------------------------------

KINDS = ("named", "unnamed", "overtaken", "passed", "cited", "uncited")
GOOD = {"named", "passed", "cited"}


@dataclass
class Seen:
    """The state of one prompt on one engine as of the last message about it."""

    day: str
    named: bool
    rank: int | None
    ahead: list[str] = field(default_factory=list)
    cited: bool = False

    @classmethod
    def from_check(cls, check: Check) -> Seen:
        return cls(check.day, check.named, check.rank, list(check.ahead), check.cited)

    def to_dict(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "named": self.named,
            "rank": self.rank,
            "ahead": self.ahead,
            "cited": self.cited,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Seen:
        return cls(
            day=str(raw.get("day") or ""),
            named=bool(raw.get("named")),
            rank=raw.get("rank"),
            ahead=[str(x) for x in raw.get("ahead") or []],
            cited=bool(raw.get("cited")),
        )


@dataclass(frozen=True)
class Change:
    kind: str  # one of KINDS
    competitor: str = ""  # for overtaken and passed

    @property
    def good(self) -> bool:
        return self.kind in GOOD


def changes(seen: Seen, check: Check, competitors: Iterable[str] = ()) -> list[Change]:
    """What differs between the told state and one answer. Competitors no longer in
    config.yml are ignored."""
    tracked = set(competitors)
    out: list[Change] = []
    if seen.named != check.named:
        out.append(Change("named" if check.named else "unnamed"))
    elif check.named:
        before = set(seen.ahead)
        for name in check.ahead:
            if name not in before and name in tracked:
                out.append(Change("overtaken", name))
        for name in seen.ahead:
            if name not in check.ahead and name in check.brands and name in tracked:
                out.append(Change("passed", name))
    if seen.cited != check.cited:
        out.append(Change("cited" if check.cited else "uncited"))
    return out


def confirmed(seen: Seen, samples: Sequence[Check], competitors: Iterable[str]) -> list[Change]:
    """The changes every answer of the round agrees on."""
    names = list(competitors)
    first = changes(seen, samples[0], names)
    rest = [changes(seen, s, names) for s in samples[1:]]
    return [c for c in first if all(c in other for other in rest)]


def advance(seen: Seen, found: Sequence[Change], samples: Sequence[Check]) -> Seen:
    """The told state after a message with ``found``; fields nobody was told about stay."""
    latest = samples[-1]
    new = replace(seen, ahead=list(seen.ahead), day=latest.day)
    for change in found:
        if change.kind == "named":
            new.named = True
            common = set(samples[0].ahead).intersection(*(s.ahead for s in samples[1:]))
            new.ahead = [n for n in samples[0].ahead if n in common]
        elif change.kind == "unnamed":
            new.named = False
            new.ahead = []
            new.rank = None
        elif change.kind == "overtaken" and change.competitor not in new.ahead:
            new.ahead.append(change.competitor)
        elif change.kind == "passed" and change.competitor in new.ahead:
            new.ahead.remove(change.competitor)
        elif change.kind in ("cited", "uncited"):
            new.cited = change.kind == "cited"
    if new.named and latest.named:
        new.rank = latest.rank
    return new


# -- weekly digest ------------------------------------------------------------------------


@dataclass
class Tally:
    answers: int = 0
    named: int = 0
    cited: int = 0
    ranks: list[int] = field(default_factory=list)

    def add(self, check: Check) -> None:
        self.answers += 1
        self.named += check.named
        self.cited += check.cited
        if check.rank is not None:
            self.ranks.append(check.rank)

    @property
    def rate(self) -> float | None:
        return self.named / self.answers if self.answers else None

    @property
    def avg_rank(self) -> float | None:
        return sum(self.ranks) / len(self.ranks) if self.ranks else None


@dataclass
class Gap:
    prompt: Prompt
    engine: str
    answers: int
    competitors: list[tuple[str, int]]  # named instead of you: (brand, answers)


@dataclass
class Weekly:
    start: date
    end: date
    total: Tally
    previous: Tally
    engines: dict[str, Tally]
    prompts: list[tuple[Prompt, dict[str, Tally]]]
    # (brand, answers naming it, answers it was tracked in), highest share first. A brand
    # is not tracked in answers to a prompt that names it.
    share: list[tuple[str, int, int]]
    gaps: list[Gap]
    sites: list[tuple[str, int]]  # domain -> answers citing it, most first


def weekly(config: Config, checks: Iterable[Check], end: date, days: int = 7) -> Weekly:
    """Sums over the first answer of each round in the ``days`` days up to ``end``.

    Rechecks are left out: they are only asked when something changed, so counting them
    would weigh changes twice.
    """
    start = end - timedelta(days=days - 1)
    prev_start = start - timedelta(days=days)
    prompts = {p.id: p for p in config.prompts}
    engines = list(config.engines)
    first = [c for c in checks if c.sample == 1 and c.prompt in prompts and c.engine in engines]
    window = [c for c in first if start.isoformat() <= c.day <= end.isoformat()]
    earlier = [c for c in first if prev_start.isoformat() <= c.day < start.isoformat()]

    total, previous = Tally(), Tally()
    by_engine = {e: Tally() for e in engines}
    by_pair: dict[tuple[str, str], Tally] = {}
    share: Counter[str] = Counter()
    asked: Counter[str] = Counter()
    tracked = {p.id: [b.name for b in tracked_for(config, p)] for p in config.prompts}
    sites: Counter[str] = Counter()
    pair_brands: dict[tuple[str, str], Counter[str]] = {}
    for c in window:
        total.add(c)
        by_engine[c.engine].add(c)
        by_pair.setdefault((c.prompt, c.engine), Tally()).add(c)
        share.update(c.brands.keys())
        asked.update(tracked[c.prompt])
        sites.update(set(c.sites))
        pair_brands.setdefault((c.prompt, c.engine), Counter()).update(c.brands.keys())
    for c in earlier:
        previous.add(c)

    rows = []
    gaps = []
    for p in config.prompts:
        cells = {e: by_pair[(p.id, e)] for e in engines if (p.id, e) in by_pair}
        if cells:
            rows.append((p, cells))
        for e, tally in cells.items():
            named = pair_brands.get((p.id, e), Counter())
            if tally.named == 0 and named:
                comps = [(n, k) for n, k in named.most_common() if n != config.brand.name]
                gaps.append(Gap(p, e, tally.answers, comps))
    order = {b.name: i for i, b in enumerate(config.brands)}
    ranked_share = sorted(
        ((b.name, share[b.name], asked[b.name]) for b in config.brands),
        key=lambda item: (-(item[1] / item[2] if item[2] else 0), order[item[0]]),
    )
    return Weekly(
        start=start,
        end=end,
        total=total,
        previous=previous,
        engines={e: t for e, t in by_engine.items() if t.answers},
        prompts=rows,
        share=ranked_share,
        gaps=gaps,
        sites=sorted(sites.items(), key=lambda item: (-item[1], item[0])),
    )
