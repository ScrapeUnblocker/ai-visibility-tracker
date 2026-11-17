"""The two messages: change alerts after a run, and the weekly digest.

Both are built as a small :class:`Doc` (a title, intro lines and sections of items) and
rendered from it: Slack mrkdwn and Discord markdown (split into posts that fit), plain text
and HTML for email, and JSON for the webhook.
"""

from __future__ import annotations

import html
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from .config import ENGINES, Config, Prompt
from .process import Change, Check, Seen, Weekly, owns

SOURCE = "ai-visibility-tracker"
MAX_GAPS = 10
MAX_SITES = 10


def plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else many or word + 's'}"


def pct(part: int, whole: int) -> str:
    return f"{round(100 * part / whole)}%" if whole else "-"


def day_text(when: datetime | date) -> str:
    return f"{when:%a} {when.day} {when:%b %Y}"


def span_text(start: date, end: date) -> str:
    if start.year != end.year:
        return f"{start.day} {start:%b %Y} - {end.day} {end:%b %Y}"
    if start.month != end.month:
        return f"{start.day} {start:%b} - {end.day} {end:%b %Y}"
    return f"{start.day}-{end.day} {end:%b %Y}"


def join_names(names: Sequence[str], limit: int = 4) -> str:
    shown = list(names[:limit])
    rest = len(names) - len(shown)
    return ", ".join(shown) + (f" +{rest} more" if rest > 0 else "")


# -- the document model -------------------------------------------------------------------


@dataclass
class Item:
    text: str
    note: str = ""  # shown under the item, e.g. the line of the answer that names you


@dataclass
class Section:
    heading: str
    items: list[Item] = field(default_factory=list)


@dataclass
class Doc:
    title: str
    subtitle: str
    intro: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    outro: str = ""


# -- change alerts ------------------------------------------------------------------------


@dataclass
class PairReport:
    """One prompt on one engine that goes into an alert: new, or with confirmed changes."""

    prompt: Prompt
    engine: str
    samples: list[Check]  # the latest round; the second one is the recheck
    seen: Seen | None  # None: the first check of this prompt on this engine
    found: list[Change] = field(default_factory=list)

    @property
    def latest(self) -> Check:
        return self.samples[-1]

    @property
    def new(self) -> bool:
        return self.seen is None


def status_text(check: Check, brand: str) -> str:
    """``named #2 of 4, after Jira · your site cited`` or ``not named (named: X, Y)``."""
    if check.named:
        text = f"named #{check.rank} of {len(check.brands)}"
        if check.ahead:
            text += f", after {join_names(check.ahead)}"
    else:
        others = [n for n in sorted(check.brands, key=check.brands.get) if n != brand]
        text = "not named" + (f" (named: {join_names(others)})" if others else "")
    if check.cited:
        text += " · your site cited"
    return text


def change_text(change: Change, check: Check, brand: str, domains: Sequence[str]) -> str:
    where = f"#{check.rank} of {len(check.brands)}" if check.rank else ""
    if change.kind == "named":
        after = f", after {join_names(check.ahead)}" if check.ahead else ""
        return f"🟢 now named: {where}{after}"
    if change.kind == "unnamed":
        others = [n for n in sorted(check.brands, key=check.brands.get) if n != brand]
        return "🔴 no longer named" + (f" (named: {join_names(others)})" if others else "")
    if change.kind == "overtaken":
        return f"🔴 {change.competitor} is now named before you (you: {where})"
    if change.kind == "passed":
        return f"🟢 you are now named before {change.competitor} (you: {where})"
    if change.kind == "cited":
        mine = [d for d in check.sites if owns(d, domains)]
        return "🟢 your site is now cited" + (f" ({', '.join(mine[:2])})" if mine else "")
    return "🔴 your site is no longer cited"


@dataclass
class Alert:
    brand: str
    domains: tuple[str, ...]
    now: datetime
    reports: list[PairReport]
    countries: bool = False  # show each prompt's country (prompts ask from several)

    kind = "changes"

    @property
    def new(self) -> list[PairReport]:
        return [r for r in self.reports if r.new]

    @property
    def changed(self) -> list[PairReport]:
        return [r for r in self.reports if r.found]

    @property
    def first_run(self) -> bool:
        return bool(self.reports) and not self.changed

    @property
    def empty(self) -> bool:
        return not self.reports

    @property
    def change_count(self) -> int:
        return sum(len(r.found) for r in self.reports)

    @property
    def subject(self) -> str:
        head = f"AI visibility · {self.brand}"
        if self.first_run:
            named = sum(r.latest.named for r in self.new)
            return f"{head}: named in {named} of {plural(len(self.new), 'answer')} (first check)"
        good = sum(c.good for r in self.reports for c in r.found)
        bad = self.change_count - good
        parts = [p for p in (f"🔴 {bad}" if bad else "", f"🟢 {good}" if good else "") if p]
        text = f"{head}: {plural(self.change_count, 'change')} ({' · '.join(parts)})"
        if self.new:
            text += f", {plural(len(self.new), 'new answer')}"
        return text

    def doc(self) -> Doc:
        if self.first_run:
            sub = f"{day_text(self.now)} · first check of {plural(len(self.new), 'answer')}"
        else:
            sub = f"{day_text(self.now)} · {plural(self.change_count, 'change')}"
            if self.new:
                sub += f" · {plural(len(self.new), 'new answer')}"
        doc = Doc(title=f"AI visibility · {self.brand}", subtitle=sub)
        if self.first_run:
            checks = [r.latest for r in self.new]
            named = sum(c.named for c in checks)
            cited = sum(c.cited for c in checks)
            doc.intro.append(
                f"Named in {named} of {plural(len(checks), 'answer')} · your site cited in {cited}"
            )
            engines = [e for e in ENGINES if any(c.engine == e for c in checks)]
            per = []
            for e in engines:
                mine = [c for c in checks if c.engine == e]
                per.append(f"{ENGINES[e]} {sum(c.named for c in mine)} of {len(mine)}")
            doc.intro.append(" · ".join(per))
            doc.outro = "From now on a message arrives only when this changes."
        sections: dict[str, Section] = {}
        for r in self.reports:
            heading = r.prompt.text
            if self.countries and r.prompt.country:
                heading += f" ({r.prompt.country})"
            section = sections.setdefault(r.prompt.id, Section(heading))
            label = ENGINES[r.engine]
            if r.found:
                text = "; ".join(
                    change_text(c, r.latest, self.brand, self.domains) for c in r.found
                )
                note = r.latest.excerpt if any(c.kind == "named" for c in r.found) else ""
                section.items.append(Item(f"{label}: {text}", f"“{note}”" if note else ""))
            else:
                section.items.append(Item(f"{label}: {status_text(r.latest, self.brand)}"))
        doc.sections = list(sections.values())
        return doc

    def data(self) -> dict[str, Any]:
        answers = []
        for r in self.reports:
            c = r.latest
            answers.append(
                {
                    "prompt": r.prompt.text,
                    "country": r.prompt.country or None,
                    "engine": r.engine,
                    "engine_name": ENGINES[r.engine],
                    "first_check": r.new,
                    "changes": [
                        {"kind": ch.kind, "competitor": ch.competitor or None} for ch in r.found
                    ],
                    "rechecked": len(r.samples) > 1,
                    "named": c.named,
                    "rank": c.rank,
                    "brands_named": c.brands,
                    "named_before_you": c.ahead,
                    "site_cited": c.cited,
                    "sites": c.sites,
                    "excerpt": c.excerpt or None,
                    "checked_at": c.at or c.round,
                }
            )
        return {
            "brand": self.brand,
            "generated_at": self.now.isoformat(),
            "change_count": self.change_count,
            "answers": answers,
        }


def build_alert(
    config: Config, reports: Sequence[PairReport], now: datetime, countries: bool = False
) -> Alert:
    return Alert(config.brand.name, config.brand.domains, now, list(reports), countries)


# -- weekly digest ------------------------------------------------------------------------


@dataclass
class DigestMessage:
    brand: str
    domains: dict[str, str]  # domain -> brand it belongs to
    week: Weekly
    now: datetime

    kind = "digest"

    @property
    def empty(self) -> bool:
        return not self.week.total.answers

    @property
    def subject(self) -> str:
        w = self.week
        return (
            f"AI visibility weekly · {self.brand}: named in "
            f"{pct(w.total.named, w.total.answers)} of answers ({span_text(w.start, w.end)})"
        )

    def doc(self) -> Doc:
        w = self.week
        t = w.total
        doc = Doc(title=f"AI visibility weekly · {self.brand}", subtitle=span_text(w.start, w.end))
        line = f"Named in {t.named} of {plural(t.answers, 'answer')} ({pct(t.named, t.answers)})"
        if w.previous.answers:
            line += f", previous 7 days {pct(w.previous.named, w.previous.answers)}"
        doc.intro.append(line)
        doc.intro.append(f"Your site cited in {t.cited} of {t.answers} ({pct(t.cited, t.answers)})")

        engines = Section("By engine")
        for e, tally in w.engines.items():
            text = (
                f"{ENGINES[e]}: named {tally.named} of {tally.answers} "
                f"({pct(tally.named, tally.answers)})"
            )
            if tally.avg_rank is not None:
                text += f" · average rank {tally.avg_rank:.1f}"
            text += f" · site cited {tally.cited}"
            engines.items.append(Item(text))
        doc.sections.append(engines)

        share = " · ".join(
            f"{name} {pct(n, asked)}" + (" (you)" if name == self.brand else "")
            for name, n, asked in w.share
        )
        doc.sections.append(Section("Answers naming each brand", [Item(share)]))

        prompts = Section("By prompt")
        for p, cells in w.prompts:
            parts = [f"{ENGINES[e]} {c.named}/{c.answers}" for e, c in cells.items()]
            prompts.items.append(Item(f"{p.text}: {' · '.join(parts)}"))
        doc.sections.append(prompts)

        if w.gaps:
            gaps = Section("Not named while competitors are")
            for g in w.gaps[:MAX_GAPS]:
                named = ", ".join(f"{n} {k}" for n, k in g.competitors[:4])
                gaps.items.append(
                    Item(f"{ENGINES[g.engine]} · {g.prompt.text}: 0 of {g.answers} ({named})")
                )
            if len(w.gaps) > MAX_GAPS:
                gaps.items.append(Item(f"+{len(w.gaps) - MAX_GAPS} more"))
            doc.sections.append(gaps)

        if w.sites:
            parts = []
            for domain, n in w.sites[:MAX_SITES]:
                owner = next((b for d, b in self.domains.items() if owns(domain, [d])), "")
                tag = " (you)" if owner == self.brand else f" ({owner})" if owner else ""
                parts.append(f"{domain} {n}{tag}")
            doc.sections.append(Section("Most cited sites", [Item(" · ".join(parts))]))
        doc.outro = (
            "Counts use the first answer of each daily check (rechecks left out). Rank is the "
            "order brands are first named in."
        )
        return doc

    def data(self) -> dict[str, Any]:
        w = self.week

        def tally(t: Any) -> dict[str, Any]:
            return {
                "answers": t.answers,
                "named": t.named,
                "site_cited": t.cited,
                "average_rank": round(t.avg_rank, 2) if t.avg_rank is not None else None,
            }

        return {
            "brand": self.brand,
            "generated_at": self.now.isoformat(),
            "start": w.start.isoformat(),
            "end": w.end.isoformat(),
            **tally(w.total),
            "previous_7_days": tally(w.previous),
            "engines": {e: tally(t) for e, t in w.engines.items()},
            "brands_named": {name: {"named": n, "answers": asked} for name, n, asked in w.share},
            "prompts": [
                {"prompt": p.text, "engines": {e: tally(c) for e, c in cells.items()}}
                for p, cells in w.prompts
            ],
            "not_named": [
                {
                    "prompt": g.prompt.text,
                    "engine": g.engine,
                    "answers": g.answers,
                    "brands_named": dict(g.competitors),
                }
                for g in w.gaps
            ],
            "sites": dict(w.sites),
        }


def build_digest(config: Config, week: Weekly, now: datetime) -> DigestMessage:
    domains = {d: b.name for b in config.brands for d in b.domains}
    return DigestMessage(config.brand.name, domains, week, now)


# -- rendering ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Style:
    name: str
    bold: Callable[[str], str]
    note: Callable[[str], str]
    escape: Callable[[str], str]
    limit: int


def _slack_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_DISCORD_SPECIAL = "\\*_~`|"


def _discord_escape(text: str) -> str:
    return "".join("\\" + c if c in _DISCORD_SPECIAL else c for c in text)


SLACK = Style(
    name="slack",
    bold=lambda t: f"*{t}*",
    note=lambda t: f"      _{t}_",
    escape=_slack_escape,
    limit=3900,
)
DISCORD = Style(
    name="discord",
    bold=lambda t: f"**{t}**",
    note=lambda t: f"-# {t}",
    escape=_discord_escape,
    limit=1990,
)
PLAIN = Style(
    name="plain",
    bold=lambda t: t,
    note=lambda t: f"  {t}",
    escape=lambda t: t,
    limit=100_000,
)


def blocks(doc: Doc, style: Style) -> list[str]:
    e = style.escape
    head = [f"👀 {style.bold(e(doc.title))} · {e(doc.subtitle)}"]
    if doc.intro:
        head.append("")
        head += [e(line) for line in doc.intro]
    out = ["\n".join(head)]
    for section in doc.sections:
        out.append("\n" + style.bold(e(section.heading)))
        for item in section.items:
            text = f"• {e(item.text)}"
            if item.note:
                text += "\n" + style.note(e(item.note))
            out.append(text)
    if doc.outro:
        out.append("\n" + e(doc.outro))
    return out


def pack(parts: Sequence[str], limit: int) -> list[str]:
    """Join blocks into as few posts as fit ``limit`` characters each."""
    chunks: list[str] = []
    current = ""
    for part in parts:
        if len(part) > limit:
            part = part[: limit - 1] + "…"
        candidate = f"{current}\n{part}" if current else part.lstrip("\n")
        if len(candidate) > limit:
            chunks.append(current)
            current = part.lstrip("\n")
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def render(doc: Doc, style: Style) -> list[str]:
    """The message as one or more posts for a chat destination."""
    return pack(blocks(doc, style), style.limit)


def render_plain(doc: Doc) -> str:
    return "\n".join(blocks(doc, PLAIN)).strip() + "\n"


_MUTED = "color:#59636e"


def render_html(doc: Doc) -> str:
    e = html.escape
    out = [
        "<div style=\"font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
        'max-width:680px;color:#1f2328;line-height:1.45">',
        f'<h2 style="margin:0 0 2px">{e(doc.title)}</h2>',
        f'<p style="margin:0 0 14px;{_MUTED}">{e(doc.subtitle)}</p>',
    ]
    for line in doc.intro:
        out.append(f'<p style="margin:0 0 6px">{e(line)}</p>')
    for section in doc.sections:
        out.append(
            '<h3 style="margin:20px 0 8px;padding-bottom:4px;border-bottom:1px solid #d1d9e0;'
            f'font-size:15px">{e(section.heading)}</h3>'
        )
        out.append('<ul style="margin:0;padding-left:18px">')
        for item in section.items:
            note = (
                f'<br><span style="font-size:13px;{_MUTED};font-style:italic">{e(item.note)}</span>'
                if item.note
                else ""
            )
            out.append(f'<li style="margin:0 0 8px">{e(item.text)}{note}</li>')
        out.append("</ul>")
    if doc.outro:
        out.append(f'<p style="margin:18px 0 0;font-size:13px;{_MUTED}">{e(doc.outro)}</p>')
    out.append("</div>")
    return "\n".join(out) + "\n"
