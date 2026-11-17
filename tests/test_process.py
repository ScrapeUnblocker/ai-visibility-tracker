from __future__ import annotations

from datetime import date

from conftest import BEHIND, GOOD, MISSING

from ai_visibility_tracker.collect import Answer
from ai_visibility_tracker.config import Brand, Config
from ai_visibility_tracker.process import (
    Change,
    Check,
    Seen,
    advance,
    changes,
    confirmed,
    excerpt,
    first_mentions,
    matcher,
    owns,
    read_answer,
    tracked_for,
    visible_text,
    weekly,
)

ROUND = "2026-11-17T07:00:00+00:00"


def read(config: Config, markdown: str, sites=(), prompt: int = 0, **kw) -> Check:
    p = config.prompts[prompt]
    answer = Answer("chatgpt", p.text, markdown, tuple(sites))
    return read_answer(answer, config, p, round_at=kw.pop("round_at", ROUND), at=ROUND, **kw)


def test_visible_text_drops_images_and_link_targets() -> None:
    text = visible_text(GOOD)
    assert "Skate park" not in text
    assert "img.test" not in text
    assert "Initech Roll" in text
    assert "initech.test" not in text


def test_matcher_whole_words_and_case() -> None:
    acme = matcher(Brand("Acme", ("Acme Cloud",)))
    assert acme.search("try acme's skates")
    assert not acme.search("Acmeville")
    assert acme.search("Acme Cloud").group(0) == "Acme Cloud"
    umbrella = matcher(Brand("Umbrella", match_case=True))
    assert not umbrella.search("an umbrella helps")
    assert umbrella.search("Umbrella Corp")


def test_first_mentions() -> None:
    found = first_mentions("Globex, then Acme, then Globex", [Brand("Acme"), Brand("Globex")])
    assert found == {"Acme": 13, "Globex": 0}


def test_excerpt_strips_markup_and_keeps_long_lines_short() -> None:
    text = "intro\n2. **Acme** - smooth | safe\nend"
    assert excerpt(text, text.index("Acme")) == "Acme - smooth safe"
    long = "word " * 100 + "Acme is great " + "word " * 100
    cut = excerpt(long, long.index("Acme"))
    assert "Acme" in cut
    assert len(cut) <= 160
    assert cut.startswith("…") and cut.endswith("…")


def test_read_answer_named_first(config: Config) -> None:
    check = read(config, GOOD, ["reviews.test", "acme.test"])
    assert check.named
    assert check.rank == 1
    assert check.brands == {"Acme": 1, "Globex": 2, "Initech": 3}
    assert check.ahead == []
    assert check.cited
    assert check.excerpt == "For beginners, my top pick is Acme."
    assert check.day == "2026-11-17"
    assert check.sample == 1


def test_read_answer_behind_a_competitor(config: Config) -> None:
    check = read(config, BEHIND, ["globex.test"])
    assert check.rank == 2
    assert check.ahead == ["Globex"]
    assert not check.cited
    assert check.excerpt.startswith("Acme Skates")


def test_read_answer_not_named(config: Config) -> None:
    check = read(config, MISSING)
    assert not check.named
    assert check.rank is None
    assert check.brands == {"Globex": 1, "Initech": 2}  # "umbrella" is lower case
    assert check.excerpt == ""


def test_competitor_named_in_the_prompt_is_not_tracked(config: Config) -> None:
    assert [b.name for b in tracked_for(config, config.prompts[1])] == [
        "Acme",
        "Initech",
        "Umbrella",
    ]
    check = read(config, BEHIND, prompt=1)
    assert check.rank == 1
    assert check.ahead == []
    assert "Globex" not in check.brands


def test_owns() -> None:
    assert owns("docs.acme.test", ["acme.test"])
    assert not owns("notacme.test", ["acme.test"])


def seen(**kw) -> Seen:
    base = {"day": "2026-11-16", "named": True, "rank": 1, "ahead": [], "cited": True}
    base.update(kw)
    return Seen(**base)


NAMES = ["Globex", "Initech", "Umbrella"]


def test_changes(config: Config) -> None:
    good = read(config, GOOD, ["acme.test"])
    behind = read(config, BEHIND)
    missing = read(config, MISSING)
    assert changes(seen(), good, NAMES) == []
    assert changes(seen(), behind, NAMES) == [Change("overtaken", "Globex"), Change("uncited")]
    assert changes(seen(ahead=["Globex"], cited=False), good, NAMES) == [
        Change("passed", "Globex"),
        Change("cited"),
    ]
    assert changes(seen(), missing, NAMES) == [Change("unnamed"), Change("uncited")]
    assert changes(seen(named=False, rank=None, cited=False), behind, NAMES) == [Change("named")]
    # a competitor removed from config.yml is ignored
    assert changes(seen(cited=False), behind, ["Initech"]) == []


def test_confirmed_needs_every_answer_to_agree(config: Config) -> None:
    good = read(config, GOOD, ["acme.test"])
    behind = read(config, BEHIND, ["acme.test"], sample=2)
    behind_again = read(config, BEHIND, ["acme.test"], sample=2)
    told = seen()
    assert confirmed(told, [behind, behind_again], NAMES) == [Change("overtaken", "Globex")]
    assert confirmed(told, [behind, good], NAMES) == []
    assert confirmed(told, [behind], NAMES) == [Change("overtaken", "Globex")]


def test_advance(config: Config) -> None:
    behind = read(config, BEHIND)
    told = seen()
    found = confirmed(told, [behind, behind], NAMES)
    new = advance(told, found, [behind, behind])
    assert new == Seen("2026-11-17", True, 2, ["Globex"], False)
    assert confirmed(new, [behind, behind], NAMES) == []  # told once, not again

    missing = read(config, MISSING)
    gone = advance(new, [Change("unnamed")], [missing])
    assert (gone.named, gone.rank, gone.ahead) == (False, None, [])

    back = advance(gone, [Change("named")], [behind, read(config, GOOD)])
    assert back.named and back.ahead == []  # Globex was ahead in one answer only


def test_seen_round_trip(config: Config) -> None:
    told = Seen.from_check(read(config, BEHIND))
    assert Seen.from_dict(told.to_dict()) == told


def test_weekly(config: Config) -> None:
    checks = [
        read(config, GOOD, ["acme.test"], round_at="2026-11-16T07:00:00+00:00"),
        read(config, BEHIND, round_at="2026-11-17T07:00:00+00:00"),
        read(config, MISSING, round_at="2026-11-17T07:00:00+00:00", prompt=1),
        read(config, MISSING, round_at="2026-11-09T07:00:00+00:00"),  # previous week
        read(config, GOOD, round_at="2026-11-17T07:00:00+00:00", sample=2),  # recheck: skipped
    ]
    week = weekly(config, checks, date(2026, 11, 17))
    assert (week.start, week.end) == (date(2026, 11, 11), date(2026, 11, 17))
    assert (week.total.answers, week.total.named, week.total.cited) == (3, 2, 1)
    assert week.total.avg_rank == 1.5
    assert (week.previous.answers, week.previous.named) == (1, 0)
    assert list(week.engines) == ["chatgpt"]
    # Globex is not tracked for the "Globex alternatives" prompt: 2 of 2, not 2 of 3
    assert week.share == [
        ("Globex", 2, 2),
        ("Acme", 2, 3),
        ("Initech", 2, 3),
        ("Umbrella", 0, 3),
    ]
    assert [(g.prompt.text, g.engine, g.competitors) for g in week.gaps] == [
        ("Globex alternatives for small teams", "chatgpt", [("Initech", 1)])
    ]
    assert week.sites == [("acme.test", 1)]
    assert [p.text for p, _ in week.prompts] == [p.text for p in config.prompts]
