"""Command line: ``ai-visibility-tracker run | digest | ask | status | test-destinations``."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, TextIO

from scrapeunblocker import Client

from . import __version__
from .collect import FATAL, AiClient, AskError, ask
from .config import ENGINES, Config, ConfigError, Prompt, load_config
from .messages import PairReport, build_alert, build_digest, render_plain, status_text
from .process import Check, Seen, advance, changes, confirmed, read_answer, visible_text, weekly
from .sinks import (
    DeliveryError,
    Destinations,
    Message,
    Sink,
    build_destinations,
    needs,
    new_http_client,
    plural_rows,
    sheet_row,
)
from .state import State, StateError, iso_week, pair_key

API_KEY_ENV = "SCRAPEUNBLOCKER_KEY"
SIGNUP_URL = (
    "https://scrapeunblocker.com/?utm_source=github&utm_medium=integration"
    "&utm_campaign=example-repos"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-visibility-tracker",
        description=(
            "Is your brand named when people ask ChatGPT, Gemini and Google AI Mode your "
            "prompts? Logs every answer to a Google Sheet, alerts Slack, Discord, email or a "
            "webhook when that changes, and sends a weekly digest. Answers come from the "
            "ScrapeUnblocker API."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-c", "--config", default="config.yml", help="config file (default: config.yml)"
    )
    common.add_argument(
        "--env-file",
        default=".env",
        help="read environment variables from this file when it exists (default: .env)",
    )
    common.add_argument("-v", "--verbose", action="store_true", help="log every API call")

    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    run = sub.add_parser(
        "run",
        parents=[common],
        help="ask every prompt not asked today, log the answers and alert on changes",
    )
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="print exactly what would be delivered; deliver nothing and save nothing",
    )
    run.add_argument(
        "--force", action="store_true", help="ask again even if a prompt was asked today (UTC)"
    )
    run.add_argument(
        "--engine",
        action="append",
        choices=list(ENGINES),
        help="only this engine; repeat for more",
    )
    run.add_argument(
        "--prompt",
        action="append",
        metavar="TEXT",
        help="only prompts containing this text; repeat for more",
    )
    digest = sub.add_parser(
        "digest", parents=[common], help="send the weekly digest now (no API calls)"
    )
    digest.add_argument("--dry-run", action="store_true", help="print it; send and save nothing")
    digest.add_argument(
        "--force", action="store_true", help="send even if this week's digest went out already"
    )
    ask_cmd = sub.add_parser(
        "ask",
        parents=[common],
        help="ask one question and show how the answers name your brands (saves nothing)",
    )
    ask_cmd.add_argument("question", help="the prompt, as a user would type it")
    ask_cmd.add_argument(
        "--engine", action="append", choices=list(ENGINES), help="only this engine; repeat"
    )
    ask_cmd.add_argument("--country", help="ask from this country, e.g. US, GB, DE")
    ask_cmd.add_argument("--show-answer", action="store_true", help="print the answer text too")
    sub.add_parser(
        "status", parents=[common], help="the last answer and the told state per prompt (no API)"
    )
    sub.add_parser(
        "test-destinations",
        parents=[common],
        help="send a test message to each destination and set up the sheet tab (no API calls)",
    )
    return parser


def load_env_file(path: str, environ: MutableMapping[str, str]) -> None:
    """Minimal ``.env`` reader: ``KEY=value`` lines; real environment variables win."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.removeprefix("export ").strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in environ:
                environ[key] = value


def annotation(level: str, title: str, message: str) -> str:
    """A GitHub Actions workflow command (``::warning title=...::...``), safely escaped."""

    def data(text: str) -> str:
        return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")

    prop = data(title).replace(":", "%3A").replace(",", "%2C")
    return f"::{level} title={prop}::{data(message)}"


def shown_path(path: Path) -> str:
    """``path`` relative to the working directory when it is inside it."""
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def short(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


# -- asking ---------------------------------------------------------------------------------


@dataclass
class Asked:
    prompt: Prompt
    engine: str
    checks: list[Check] = field(default_factory=list)
    calls: int = 0
    error: AskError | None = None
    note: str = ""


def ask_engine(
    config: Config,
    client: AiClient,
    engine: str,
    prompts: Sequence[Prompt],
    state: State,
    *,
    round_at: str,
    clock: Callable[[], str],
    sleep: Callable[[float], None] | None = None,
) -> list[Asked]:
    """Ask one engine every prompt in turn. A change against the told state is asked a
    second time (the recheck) before it can be delivered."""
    names = [c.name for c in config.competitors]
    out: list[Asked] = []
    for p in prompts:
        item = Asked(p, engine)
        out.append(item)
        try:
            answer, calls = ask(
                client, engine, p.text, country=p.country, language=config.language, sleep=sleep
            )
        except AskError as exc:
            item.calls, item.error = exc.calls, exc
            continue
        item.calls = calls
        first = read_answer(answer, config, p, round_at=round_at, at=clock())
        item.checks.append(first)
        seen = state.baseline.get(pair_key(p.id, engine))
        if not (config.checks.recheck and seen is not None and changes(seen, first, names)):
            continue
        try:
            again, calls = ask(
                client, engine, p.text, country=p.country, language=config.language, sleep=sleep
            )
        except AskError as exc:
            item.calls += exc.calls
            item.note = "recheck failed, so no alert yet"
            continue
        item.calls += calls
        second = read_answer(again, config, p, round_at=round_at, at=clock(), sample=2)
        item.checks.append(second)
        agreed = confirmed(seen, [first, second], names)
        item.note = (
            f"recheck confirmed {len(agreed)} change(s)"
            if agreed
            else "recheck answer disagrees, so no alert"
        )
    return out


def ask_all(
    config: Config,
    client_factory: Callable[[], AiClient],
    due: Sequence[tuple[Prompt, str]],
    state: State,
    *,
    round_at: str,
    clock: Callable[[], str],
    sleep: Callable[[float], None] | None = None,
) -> list[Asked]:
    """The engines run side by side (one client each); prompts run in turn on each."""
    engines = list(dict.fromkeys(e for _, e in due))
    with ThreadPoolExecutor(max_workers=max(1, len(engines))) as pool:
        futures = {
            e: pool.submit(
                ask_engine,
                config,
                client_factory(),
                e,
                [p for p, pe in due if pe == e],
                state,
                round_at=round_at,
                clock=clock,
                sleep=sleep,
            )
            for e in engines
        }
        results = {e: f.result() for e, f in futures.items()}
    by_pair = {(a.prompt.id, a.engine): a for items in results.values() for a in items}
    return [by_pair[(p.id, e)] for p, e in due]


def describe(item: Asked, brand: str) -> str:
    if item.error:
        return f"no answer: {item.error}"
    text = status_text(item.checks[0], brand)
    if item.note:
        text += f"\n{'':<18}↳ {item.note}"
    return text


# -- what to deliver ------------------------------------------------------------------------


def pending(config: Config, state: State) -> tuple[list[PairReport], int]:
    """The answers a message should be about: first checks, and confirmed changes against
    the told state. Also returns how many prompts have a change still waiting for an
    agreeing second answer."""
    names = [c.name for c in config.competitors]
    reports: list[PairReport] = []
    waiting = 0
    for p in config.prompts:
        for e in config.engines:
            samples = state.round_of(p.id, e)
            if not samples:
                continue
            seen = state.baseline.get(pair_key(p.id, e))
            if seen is None:
                reports.append(PairReport(p, e, samples[:1], None))
                continue
            if config.checks.recheck and len(samples) == 1:
                waiting += bool(changes(seen, samples[0], names))
                continue
            found = confirmed(seen, samples, names)
            if found:
                reports.append(PairReport(p, e, samples, seen, found))
    return reports, waiting


def mark_told(state: State, reports: Sequence[PairReport]) -> None:
    for r in reports:
        key = pair_key(r.prompt.id, r.engine)
        if r.seen is None:
            state.baseline[key] = Seen.from_check(r.samples[0])
        else:
            state.baseline[key] = advance(r.seen, r.found, r.samples)


def deliver(message: Message, sinks: Sequence[Sink], *, err: TextIO) -> tuple[bool, list[str]]:
    """Send to every sink. Returns ``(at least one took it, names of sinks that failed)``."""
    ok = False
    failed = []
    for sink in sinks:
        try:
            sink.send(message)
        except DeliveryError as exc:
            print(f"Delivery failed: {exc}", file=err)
            failed.append(sink.name)
        else:
            ok = True
    return ok, failed


def digest_due(config: Config, state: State, today: date) -> bool:
    """On the first run on or after ``digest.day`` each week, once there are checks from
    before today."""
    weekday = config.digest.weekday
    if weekday is None or state.digest_week == iso_week(today) or today.weekday() < weekday:
        return False
    first = state.first_day()
    return bool(first) and first < today.isoformat()


def prompt_text(state: State, config: Config, prompt_id: str) -> tuple[str, str]:
    for p in config.prompts:
        if p.id == prompt_id:
            return p.text, p.country
    saved = state.prompts.get(prompt_id) or {}
    return saved.get("text", prompt_id), saved.get("country", "")


# -- run ----------------------------------------------------------------------------------


def run_checks(
    config: Config,
    client_factory: Callable[[], AiClient],
    dests: Destinations,
    *,
    dry_run: bool,
    now: datetime,
    force: bool = False,
    engines: Sequence[str] | None = None,
    prompts: Sequence[Prompt] | None = None,
    clock: Callable[[], str] = _now_iso,
    out: TextIO = sys.stdout,
    err: TextIO = sys.stderr,
    annotate: bool = False,
    summary_path: str | None = None,
    sleep: Callable[[float], None] | None = None,
) -> int:
    """One scheduled run: ask, read, log to the sheet, alert on changes, send the digest
    when it is due, save. Returns the exit code."""
    today = now.date()
    state = State.load(config.state, brand=config.brand.name)
    state.remember_prompts(config)
    use_engines = [e for e in config.engines if not engines or e in engines]
    use_prompts = list(prompts or config.prompts)
    due = [
        (p, e)
        for p in use_prompts
        for e in use_engines
        if force or not state.checked_on(p.id, e, today.isoformat())
    ]
    brand = config.brand.name
    labels = ", ".join(ENGINES[e] for e in use_engines)
    recheck = ", plus one recheck per change" if config.checks.recheck and due else ""
    print(
        f"Asking {len(use_prompts)} prompt(s) on {labels} for {brand}: "
        f"{len(due)} API call(s){recheck}.",
        file=out,
        flush=True,
    )
    exit_code = 0
    calls = 0
    if not due:
        print(
            "  Every prompt was asked today (UTC) already, so no API calls. --force asks again.",
            file=out,
        )
    else:
        asked = ask_all(
            config,
            client_factory,
            due,
            state,
            round_at=now.isoformat(),
            clock=clock,
            sleep=sleep,
        )
        width = 42
        for item in asked:
            calls += item.calls
            label = f"{ENGINES[item.engine]:<15}"
            print(
                f"  {label} {short(item.prompt.text, width):<{width}}  {describe(item, brand)}",
                file=out,
            )
            if item.error and annotate:
                level = "warning" if item.error.permanent else "notice"
                title = f"{ENGINES[item.engine]} not asked"
                print(annotation(level, title, f"{item.prompt.text}: {item.error}"), file=out)
            state.add(item.checks)
        print(f"API calls used: {calls}", file=out)
        errors = [a for a in asked if a.error]
        if any(a.error.permanent for a in errors if a.error) or len(errors) == len(asked):
            exit_code = 1

    # 1. the sheet: one row per answer not written yet
    print(file=out)
    rows_for = [c for c in state.checks if not c.sheet] if config.sheet.enabled else []
    rows = [sheet_row(c, *prompt_text(state, config, c.prompt)) for c in rows_for]
    if rows:
        if dry_run:
            if dests.sheet:
                print(f"Dry run: would append {dests.sheet.preview(rows)}", file=out)
            else:
                print(
                    f"Dry run: {plural_rows(len(rows))} would wait for the Google Sheet.", file=out
                )
        elif dests.sheet is None:
            print(
                f"{plural_rows(len(rows))} wait for the Google Sheet ({needs('sheet')} not set).",
                file=out,
            )
        else:
            try:
                dests.sheet.append(rows)
            except DeliveryError as exc:
                exit_code = 1
                print(f"Delivery failed: {exc}", file=err)
                print("The rows are written on the next run.", file=out)
                if annotate:
                    print(annotation("warning", "Google Sheet", str(exc)), file=out)
            else:
                for c in rows_for:
                    c.sheet = True
                print(
                    f"Google Sheet: appended {plural_rows(len(rows))} to {config.sheet.tab}.",
                    file=out,
                )

    # 2. alerts: first checks and confirmed changes
    reports, waiting = pending(config, state)
    countries = len({p.country for p in config.prompts}) > 1
    alert = build_alert(config, reports, now, countries)
    if waiting:
        print(f"{waiting} change(s) wait for an agreeing second answer.", file=out)
    if alert.empty:
        print("No changes to deliver.", file=out)
    elif dry_run:
        print(f"Dry run: would deliver {alert.subject}", file=out)
        if not dests.alerts:
            print("No alert destination is set up; the message would be:", file=out)
            print(render_plain(alert.doc()), file=out)
        for sink in dests.alerts:
            print(f"\n--- {sink.name} ---\n{sink.preview(alert)}", file=out)
    elif not config.alerts.to:
        mark_told(state, reports)
        print(f"Alerts are off (alerts.to is empty): {alert.subject}", file=out)
    elif not dests.alerts:
        print(
            f"Waiting: {alert.subject}. No alert destination is set up; it is delivered on the "
            "first run after you add one.",
            file=out,
        )
    else:
        ok, failed = deliver(alert, dests.alerts, err=err)
        took = ", ".join(s.name for s in dests.alerts if s.name not in failed) or "nowhere"
        if ok:
            mark_told(state, reports)
            print(f"Delivered to {took}: {alert.subject}", file=out)
        else:
            print("Not delivered anywhere. The same changes are tried again next run.", file=out)
        if failed:
            exit_code = 1
            if annotate:
                names = ", ".join(sorted(failed))
                print(
                    annotation("warning", "Delivery failed", f"Not accepted by {names}"), file=out
                )

    # 3. the weekly digest
    if digest_due(config, state, today):
        code = send_digest(config, state, dests, now=now, dry_run=dry_run, out=out, err=err)
        exit_code = max(exit_code, code)

    if summary_path:
        _write_summary(summary_path, config, state)
    if dry_run:
        print("Dry run: nothing was sent or saved.", file=out)
        return exit_code
    state.prune(today, config.checks.history_days, config)
    if state.save(config.state):
        print(f"Saved {config.state.name}.", file=out)
    return exit_code


def send_digest(
    config: Config,
    state: State,
    dests: Destinations,
    *,
    now: datetime,
    dry_run: bool,
    out: TextIO,
    err: TextIO,
) -> int:
    week = weekly(config, state.checks, now.date())
    message = build_digest(config, week, now)
    if message.empty:
        print("Weekly digest: no checks in the last 7 days yet.", file=out)
        return 0
    if dry_run:
        print(f"\nDry run: would send the weekly digest: {message.subject}", file=out)
        if not dests.digest:
            print(render_plain(message.doc()), file=out)
        for sink in dests.digest:
            print(f"\n--- {sink.name} ---\n{sink.preview(message)}", file=out)
        return 0
    if not dests.digest:
        print("Weekly digest: no digest destination is set up (digest.to).", file=out)
        return 0
    ok, failed = deliver(message, dests.digest, err=err)
    if ok:
        state.digest_week = iso_week(now.date())
        took = ", ".join(s.name for s in dests.digest if s.name not in failed)
        print(f"Weekly digest delivered to {took}: {message.subject}", file=out)
    else:
        print("Weekly digest not delivered anywhere; tried again next run.", file=out)
    return 1 if failed else 0


def _write_summary(path: str, config: Config, state: State) -> None:
    head = "| Prompt | " + " | ".join(ENGINES[e] for e in config.engines) + " |"
    lines = [
        f"### AI visibility · {config.brand.name}",
        "",
        head,
        "|---|" + "---|" * len(config.engines),
    ]
    for p in config.prompts:
        cells = []
        for e in config.engines:
            samples = state.round_of(p.id, e)
            if not samples:
                cells.append("not asked yet")
                continue
            c = samples[0]
            cell = f"#{c.rank} of {len(c.brands)}" if c.named else "not named"
            if c.cited:
                cell += ", site cited"
            cells.append(f"{cell} ({c.day})")
        lines.append(f"| {p.text.replace('|', '/')} | " + " | ".join(cells) + " |")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


# -- other commands -----------------------------------------------------------------------


def ask_once(
    config: Config,
    client: AiClient,
    args: argparse.Namespace,
    out: TextIO,
    sleep: Callable[[float], None] | None = None,
) -> int:
    country = (args.country or config.country).upper()
    prompt = Prompt(text=" ".join(args.question.split()), country=country)
    if not prompt.text:
        print("error: give a question to ask", file=sys.stderr)
        return 2
    calls = 0
    code = 0
    for engine in args.engine or config.engines:
        started = time.monotonic()
        try:
            answer, used = ask(
                client, engine, prompt.text, country=country, language=config.language, sleep=sleep
            )
        except AskError as exc:
            calls += exc.calls
            code = 1
            print(f"{ENGINES[engine]}: no answer: {exc}\n", file=out)
            continue
        calls += used
        took = time.monotonic() - started
        now = _now_iso()
        c = read_answer(answer, config, prompt, round_at=now, at=now)
        search = {True: "yes", False: "no", None: "?"}[answer.web_search]
        print(
            f"{ENGINES[engine]} ({country or 'any country'}) · web search: {search} · {took:.0f} s",
            file=out,
        )
        print(f"  {status_text(c, config.brand.name)}", file=out)
        if c.brands:
            named = ", ".join(f"{n} #{r}" for n, r in sorted(c.brands.items(), key=lambda x: x[1]))
            print(f"  brands named: {named}", file=out)
        if c.excerpt:
            print(f"  first named in: “{c.excerpt}”", file=out)
        if c.sites:
            print(f"  sites: {', '.join(c.sites)}", file=out)
        if args.show_answer:
            text = "\n".join(line for line in visible_text(answer.markdown).splitlines() if line)
            print("\n" + short(text, 4000), file=out)
        print(file=out)
    print(f"API calls used: {calls}. Nothing was saved.", file=out)
    return code


def show_status(config: Config, out: TextIO, today: date) -> int:
    state = State.load(config.state, brand=config.brand.name)
    first = state.first_day()
    since = f" since {first}" if first else ""
    digest = f" · last digest {state.digest_week}" if state.digest_week else ""
    where = shown_path(config.state)
    print(f"State: {where} · {len(state.checks)} answer(s){since}{digest}", file=out)
    week = weekly(config, state.checks, today)
    for p in config.prompts:
        print(f"\n{p.text}" + (f" ({p.country})" if p.country else ""), file=out)
        for e in config.engines:
            samples = state.round_of(p.id, e)
            label = f"{ENGINES[e]:<15}"
            if not samples:
                print(f"  {label} not asked yet", file=out)
                continue
            c = samples[0]
            tally = next((t[e] for q, t in week.prompts if q.id == p.id and e in t), None)
            last7 = f" · named in {tally.named} of {tally.answers} in 7 days" if tally else ""
            seen = state.baseline.get(pair_key(p.id, e))
            told = "" if seen else " · not delivered yet"
            print(f"  {label} {c.day}: {status_text(c, config.brand.name)}{last7}{told}", file=out)
    return 0


def test_destinations(dests: Destinations, out: TextIO) -> int:
    for name in dests.skipped:
        print(f"  {name:<8} skipped ({needs(name)} not set)", file=out)
    failed = 0
    for sink in dests.all:
        try:
            result = sink.test()
        except DeliveryError as exc:
            failed += 1
            print(f"  {sink.name:<8} FAILED {exc}", file=out)
        else:
            print(f"  {sink.name:<8} ok, {result}", file=out)
    return 1 if failed else 0


def _make_client(environ: Mapping[str, str]) -> Client:
    # The SDK's own retries are off: ask() retries once, after a pause.
    return Client(api_key=environ[API_KEY_ENV].strip(), timeout=240.0, max_retries=0)


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: MutableMapping[str, str] | None = None,
    client_factory: Callable[[Mapping[str, str]], AiClient] = _make_client,
    http_factory: Callable[[], Any] = new_http_client,
    now: datetime | None = None,
    clock: Callable[[], str] = _now_iso,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    environ = os.environ if environ is None else environ
    out = out or sys.stdout
    err = err or sys.stderr
    for stream in (out, err):
        if hasattr(stream, "reconfigure"):
            # Answers can hold any character; never crash on a narrow console.
            stream.reconfigure(errors="replace")
    now = now or datetime.now(UTC).replace(microsecond=0)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    # httpx logs full request URLs at INFO, and webhook URLs are secrets.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    load_env_file(args.env_file, environ)
    has_key = bool((environ.get(API_KEY_ENV) or "").strip())
    try:
        config = load_config(args.config)
        if args.command == "status":
            return show_status(config, out, now.date())
        if args.command in ("run", "ask") and not has_key:
            print(
                f"error: set {API_KEY_ENV} to your ScrapeUnblocker API key "
                f"(get one at {SIGNUP_URL})",
                file=err,
            )
            return 2
        if args.command == "ask":
            return ask_once(config, client_factory(environ), args, out)

        http = http_factory()
        try:
            dests = build_destinations(config, environ, http)
            if args.command == "test-destinations":
                if not dests.all:
                    wanted = "; ".join(needs(n) for n in dests.skipped)
                    print(f"error: no destination is set up. Set one of: {wanted}", file=err)
                    return 2
                return test_destinations(dests, out)
            if dests.skipped:
                print(
                    f"(not set up, skipped: {', '.join(dests.skipped)}. `test-destinations` "
                    "lists the secrets each one needs.)",
                    file=out,
                )
            if args.command == "digest":
                state = State.load(config.state, brand=config.brand.name)
                if state.digest_week == iso_week(now.date()) and not args.force:
                    print(
                        f"This week's digest ({state.digest_week}) went out already. "
                        "--force sends it again.",
                        file=out,
                    )
                    return 0
                code = send_digest(
                    config, state, dests, now=now, dry_run=args.dry_run, out=out, err=err
                )
                if not args.dry_run and state.save(config.state):
                    print(f"Saved {config.state.name}.", file=out)
                return code
            only = None
            if args.prompt:
                only = []
                for text in args.prompt:
                    matches = config.find_prompts(text)
                    if not matches:
                        raise ConfigError(f"--prompt {text!r} matches no prompt in config.yml")
                    only += [p for p in matches if p not in only]
            return run_checks(
                config,
                lambda: client_factory(environ),
                dests,
                dry_run=args.dry_run,
                now=now,
                force=args.force,
                engines=args.engine,
                prompts=only,
                clock=clock,
                out=out,
                err=err,
                annotate=environ.get("GITHUB_ACTIONS") == "true",
                summary_path=environ.get("GITHUB_STEP_SUMMARY") or None,
            )
        finally:
            close = getattr(http, "close", None)
            if callable(close):
                close()
    except (ConfigError, StateError, DeliveryError) as exc:
        print(f"error: {exc}", file=err)
        return 2
    except FATAL as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=err)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
