from __future__ import annotations

from datetime import date

from conftest import BEHIND, GOOD, MISSING, NOW

from ai_visibility_tracker.collect import Answer
from ai_visibility_tracker.config import Config
from ai_visibility_tracker.messages import (
    DISCORD,
    SLACK,
    PairReport,
    build_alert,
    build_digest,
    pack,
    render,
    render_html,
    render_plain,
    span_text,
    status_text,
)
from ai_visibility_tracker.process import Change, Check, Seen, read_answer, weekly

ROUND = "2026-11-17T07:00:00+00:00"


def read(config: Config, markdown: str, engine="chatgpt", sites=(), prompt=0, **kw) -> Check:
    p = config.prompts[prompt]
    answer = Answer(engine, p.text, markdown, tuple(sites))
    return read_answer(answer, config, p, round_at=kw.pop("round_at", ROUND), at=ROUND, **kw)


def first_check(config: Config):
    reports = [
        PairReport(config.prompts[0], "chatgpt", [read(config, GOOD, sites=["acme.test"])], None),
        PairReport(config.prompts[0], "gemini", [read(config, BEHIND, "gemini")], None),
        PairReport(config.prompts[1], "chatgpt", [read(config, MISSING, prompt=1)], None),
    ]
    return build_alert(config, reports, NOW)


def test_status_text(config: Config) -> None:
    brand = config.brand.name
    assert status_text(read(config, GOOD, sites=["acme.test"]), brand) == (
        "named #1 of 3 · your site cited"
    )
    assert status_text(read(config, BEHIND), brand) == "named #2 of 2, after Globex"
    assert status_text(read(config, MISSING), brand) == "not named (named: Globex, Initech)"


def test_first_check_alert(config: Config) -> None:
    alert = first_check(config)
    assert alert.first_run
    assert alert.subject == "AI visibility · Acme: named in 2 of 3 answers (first check)"
    text = render_plain(alert.doc())
    assert text == (
        "👀 AI visibility · Acme · Tue 17 Nov 2026 · first check of 3 answers\n"
        "\n"
        "Named in 2 of 3 answers · your site cited in 1\n"
        "ChatGPT 1 of 2 · Gemini 1 of 1\n"
        "\n"
        "best rocket skates for beginners\n"
        "• ChatGPT: named #1 of 3 · your site cited\n"
        "• Gemini: named #2 of 2, after Globex\n"
        "\n"
        "Globex alternatives for small teams\n"
        "• ChatGPT: not named (named: Initech)\n"
        "\n"
        "From now on a message arrives only when this changes.\n"
    )


def change_alert(config: Config):
    told = Seen("2026-11-16", True, 1, [], True)
    behind = read(config, BEHIND, "google_ai_mode")
    named = read(config, GOOD, "gemini", sites=["docs.acme.test"])
    reports = [
        PairReport(
            config.prompts[0],
            "google_ai_mode",
            [behind, behind],
            told,
            [Change("overtaken", "Globex"), Change("uncited")],
        ),
        PairReport(
            config.prompts[0],
            "gemini",
            [named, named],
            Seen("2026-11-16", False, None, [], False),
            [Change("named"), Change("cited")],
        ),
    ]
    return build_alert(config, reports, NOW)


def test_change_alert(config: Config) -> None:
    alert = change_alert(config)
    assert not alert.first_run
    assert alert.change_count == 4
    assert alert.subject == "AI visibility · Acme: 4 changes (🔴 2 · 🟢 2)"
    text = render_plain(alert.doc())
    assert (
        "• Google AI Mode: 🔴 Globex is now named before you (you: #2 of 2); 🔴 your site" in text
    )
    assert "• Gemini: 🟢 now named: #1 of 3; 🟢 your site is now cited (docs.acme.test)" in text
    assert "  “For beginners, my top pick is Acme.”" in text
    data = alert.data()
    assert data["change_count"] == 4
    assert data["answers"][0]["changes"] == [
        {"kind": "overtaken", "competitor": "Globex"},
        {"kind": "uncited", "competitor": None},
    ]
    assert data["answers"][0]["rechecked"] is True
    assert data["answers"][1]["named_before_you"] == []


def test_slack_and_discord_render(config: Config) -> None:
    doc = change_alert(config).doc()
    slack = render(doc, SLACK)[0]
    assert slack.startswith("👀 *AI visibility · Acme*")
    assert "      _“For beginners" in slack
    discord = render(doc, DISCORD)[0]
    assert discord.startswith("👀 **AI visibility · Acme**")
    assert "-# “For beginners" in discord


def test_escaping(config: Config) -> None:
    doc = first_check(config).doc()
    doc.sections[0].heading = "a <b> & *c*"
    assert "*a &lt;b&gt; &amp; *c**" in render(doc, SLACK)[0]
    assert "**a <b> & \\*c\\***" in render(doc, DISCORD)[0]
    assert "a &lt;b&gt; &amp; *c*" in render_html(doc)


def test_pack_splits_long_messages() -> None:
    parts = ["head"] + [f"• item {i} " + "x" * 80 for i in range(60)]
    posts = pack(parts, 1990)
    assert len(posts) > 1
    assert all(len(p) <= 1990 for p in posts)
    assert "".join(posts).count("• item") == 60


def test_digest(config: Config) -> None:
    checks = [
        read(
            config, GOOD, sites=["acme.test", "globex.test"], round_at="2026-11-16T07:00:00+00:00"
        ),
        read(config, BEHIND, "gemini", round_at="2026-11-16T07:00:00+00:00"),
        read(config, MISSING, prompt=1, round_at="2026-11-16T07:00:00+00:00"),
    ]
    message = build_digest(config, weekly(config, checks, date(2026, 11, 16)), NOW)
    assert not message.empty
    assert (
        message.subject == "AI visibility weekly · Acme: named in 67% of answers (10-16 Nov 2026)"
    )
    text = render_plain(message.doc())
    assert "Named in 2 of 3 answers (67%)\nYour site cited in 1 of 3 (33%)" in text
    assert "• ChatGPT: named 1 of 2 (50%) · average rank 1.0 · site cited 1" in text
    assert "• Globex 100% · Acme 67% (you) · Initech 67% · Umbrella 0%" in text
    assert "• Globex alternatives for small teams: ChatGPT 0/1" in text
    assert "Not named while competitors are\n• ChatGPT · Globex alternatives" in text
    assert "acme.test 1 (you) · globex.test 1 (Globex)" in text
    data = message.data()
    assert data["brands_named"]["Globex"] == {"named": 2, "answers": 2}
    assert data["not_named"][0]["brands_named"] == {"Initech": 1}


def test_empty_digest(config: Config) -> None:
    message = build_digest(config, weekly(config, [], date(2026, 11, 16)), NOW)
    assert message.empty


def test_span_text() -> None:
    assert span_text(date(2026, 11, 11), date(2026, 11, 17)) == "11-17 Nov 2026"
    assert span_text(date(2026, 10, 28), date(2026, 11, 3)) == "28 Oct - 3 Nov 2026"
    assert span_text(date(2026, 12, 29), date(2027, 1, 4)) == "29 Dec 2026 - 4 Jan 2027"
