# AI visibility tracker

For marketing, SEO and founders: see whether ChatGPT, Gemini and Google AI Mode name your brand when people ask the questions your buyers ask. Every answer is logged to a Google Sheet each day. Slack, Discord, email or a webhook get a message only when your visibility changes: you appear or drop out, a competitor is now named before you, or your site starts or stops being cited.

[![CI](https://github.com/ScrapeUnblocker/ai-visibility-tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/ScrapeUnblocker/ai-visibility-tracker/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![Powered by ScrapeUnblocker](https://img.shields.io/badge/powered%20by-ScrapeUnblocker-6c47ff.svg)](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos)

It runs on a GitHub Actions schedule in your own copy of this repo, so there's nothing to host. The answers come from the [ScrapeUnblocker](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos) ChatGPT, Gemini and Google AI Mode APIs: one call per prompt and engine per day.

A rank tracker shows where your page sits in the blue links. It doesn't show whether an AI assistant recommends you, in what order, next to which competitors, or whether it cites your site. Answers also vary between identical questions, just as they do when a person asks. So this tracker asks every day, confirms a change with a second answer before it alerts you, and sums the week up as the share of answers that name each brand.

## What actually arrives

This is a real message, delivered in a test run on 17 Nov 2026 with the shipped `config.yml`. The example brand is Linear, an issue tracker, ranked against Jira, GitHub Projects, ClickUp, Asana and Shortcut. This copy is the plain text (Slack and Discord get the same content with bold headings):

```text
Subject: AI visibility · Linear: named in 9 of 9 answers (first check)

👀 AI visibility · Linear · Tue 17 Nov 2026 · first check of 9 answers

Named in 9 of 9 answers · your site cited in 3
ChatGPT 3 of 3 · Gemini 3 of 3 · Google AI Mode 3 of 3

best project management tool for a small software team
• ChatGPT: named #1 of 4 · your site cited
• Gemini: named #1 of 4
• Google AI Mode: named #1 of 3

what are the best Jira alternatives for startups
• ChatGPT: named #1 of 5 · your site cited
• Gemini: named #1 of 2
• Google AI Mode: named #1 of 5

which issue tracker should a 10-person engineering team use
• ChatGPT: named #1 of 3 · your site cited
• Gemini: named #2 of 4, after Jira
• Google AI Mode: named #1 of 4

From now on a message arrives only when this changes.
```

"#1 of 4" means Linear was the first of 4 tracked brands the answer named. In the "Jira alternatives" prompt, Jira itself isn't ranked, because every answer repeats the name from the question.

After that, a message comes only when something changes, and only once a second answer agrees. To show one, the test run set the stored state of one prompt back to "not named, site not cited" and asked again. The real ChatGPT answer named Linear first and linked linear.app, the recheck agreed, and this went out:

```text
Subject: AI visibility · Linear: 2 changes (🟢 2)

👀 AI visibility · Linear · Tue 17 Nov 2026 · 2 changes

which issue tracker should a 10-person engineering team use
• ChatGPT: 🟢 now named: #1 of 4; 🟢 your site is now cited (linear.app)
  “For a 10-person engineering team, my default recommendation is Linear.”
```

A drop reads like `🔴 no longer named (named: Jira, ClickUp)`, `🔴 Jira is now named before you (you: #2 of 4)` or `🔴 your site is no longer cited`. Those are templates, not results from the test.

The **Google Sheet** gets one row per answer, with the full history to filter, chart or pivot. These are four rows from the same run (the columns *Checked at*, *Country*, *Named before you* and *Check* are left out here):

| Date | Prompt | Engine | Named | Rank | Brands named | Your site cited | Sites cited | Excerpt |
|---|---|---|---|---|---|---|---|---|
| 2026-11-17 | best project management tool for a small software team | ChatGPT | TRUE | 1 | Linear #1, Jira #2, GitHub Projects #3, ClickUp #4 | TRUE | codetoolpilot.com, linear.app, atlassian.com, github.com, clickup.com, trello.com | For a small software development team (roughly 3–15 people), I'd recommend Linear as the best overall project management tool. |
| 2026-11-17 | best project management tool for a small software team | Gemini | TRUE | 1 | Linear #1, GitHub Projects #2, ClickUp #3, Jira #4 | FALSE | reddit.com, youtube.com, teamwork.com, project-management.com | Linear — Best Overall for Speed and Developer Experience |
| 2026-11-17 | best project management tool for a small software team | Google AI Mode | TRUE | 1 | Linear #1, Jira #2, ClickUp #3 | FALSE | reddit.com | Linear — Best for speed and modern software engineering |
| 2026-11-17 | what are the best Jira alternatives for startups | ChatGPT | TRUE | 1 | Linear #1, Shortcut #2, ClickUp #3, GitHub Projects #4, Asana #5 | TRUE | techpresso.co, linear.app, shortcut.com, clickup.com, jetbrains.com, github.com, plane.so, asana.com | For most startups, Linear is the best Jira alternative, particularly if you're building a software or SaaS company. It's faster, cleaner, easier to adopt, and… |

The **weekly digest** goes to Slack, Discord, email and the webhook on the first run on or after Monday. This one is from the same test, so its week holds one day of answers (the email is HTML with the same content):

```text
Subject: AI visibility weekly · Linear: named in 100% of answers (11-17 Nov 2026)

👀 AI visibility weekly · Linear · 11-17 Nov 2026

Named in 11 of 11 answers (100%)
Your site cited in 4 of 11 (36%)

By engine
• ChatGPT: named 4 of 4 (100%) · average rank 1.0 · site cited 4
• Gemini: named 4 of 4 (100%) · average rank 1.2 · site cited 0
• Google AI Mode: named 3 of 3 (100%) · average rank 1.0 · site cited 0

Answers naming each brand
• Linear 100% (you) · Jira 100% · GitHub Projects 82% · ClickUp 64% · Shortcut 45% · Asana 18%

By prompt
• best project management tool for a small software team: ChatGPT 1/1 · Gemini 1/1 · Google AI Mode 1/1
• what are the best Jira alternatives for startups: ChatGPT 1/1 · Gemini 1/1 · Google AI Mode 1/1
• which issue tracker should a 10-person engineering team use: ChatGPT 2/2 · Gemini 2/2 · Google AI Mode 1/1

Most cited sites
• atlassian.com 4 (Jira) · github.com 4 · linear.app 4 (you) · reddit.com 4 · clickup.com 2 (ClickUp) · issuelinker.com 2 · jetbrains.com 2 · plane.so 2 · shortcut.com 2 (Shortcut) · asana.com 1 (Asana)

Counts use the first answer of each daily check (rechecks left out). Rank is the order brands are first named in.
```

When a prompt never names you in a week while competitors are named, the digest adds a "Not named while competitors are" section with those prompts. "Most cited sites" shows the pages AI answers lean on, so those are the sites worth getting onto.

The **webhook** gets every field as JSON, one POST per message. This is the change message above, with the text cut short (`…`):

```json
{
  "source": "ai-visibility-tracker",
  "kind": "changes",
  "subject": "AI visibility · Linear: 2 changes (🟢 2)",
  "text": "👀 AI visibility · Linear · Tue 17 Nov 2026 · 2 changes\n\n…",
  "brand": "Linear",
  "generated_at": "2026-11-17T19:31:42+00:00",
  "change_count": 2,
  "answers": [
    {
      "prompt": "which issue tracker should a 10-person engineering team use",
      "country": "US",
      "engine": "chatgpt",
      "engine_name": "ChatGPT",
      "first_check": false,
      "changes": [
        { "kind": "named", "competitor": null },
        { "kind": "cited", "competitor": null }
      ],
      "rechecked": true,
      "named": true,
      "rank": 1,
      "brands_named": { "Linear": 1, "Jira": 2, "GitHub Projects": 3, "Shortcut": 4 },
      "named_before_you": [],
      "site_cited": true,
      "sites": ["stackfyi.com", "saassoftwaretools.com", "beancount.io", "linear.app", "atlassian.com", "github.com", "shortcut.com"],
      "excerpt": "For a 10-person engineering team, my default recommendation is Linear.",
      "checked_at": "2026-11-17T19:32:21+00:00"
    }
  ]
}
```

The weekly digest arrives with `"kind": "digest"` and its numbers as fields.

The run log from the same test, the first run and then the next one:

```text
Asking 3 prompt(s) on ChatGPT, Gemini, Google AI Mode for Linear: 9 API call(s), plus one recheck per change.
  ChatGPT         best project management tool for a small …  named #1 of 4 · your site cited
  Gemini          best project management tool for a small …  named #1 of 4
  Google AI Mode  best project management tool for a small …  named #1 of 3
  ChatGPT         what are the best Jira alternatives for s…  named #1 of 5 · your site cited
  Gemini          what are the best Jira alternatives for s…  named #1 of 2
  Google AI Mode  what are the best Jira alternatives for s…  named #1 of 5
  ChatGPT         which issue tracker should a 10-person en…  named #1 of 3 · your site cited
  Gemini          which issue tracker should a 10-person en…  named #2 of 4, after Jira
  Google AI Mode  which issue tracker should a 10-person en…  named #1 of 4
API calls used: 9

Google Sheet: appended 9 rows to Answers.
Delivered to slack, discord, webhook: AI visibility · Linear: named in 9 of 9 answers (first check)
Saved visibility.json.
```

```text
Asking 3 prompt(s) on ChatGPT, Gemini, Google AI Mode for Linear: 0 API call(s).
  Every prompt was asked today (UTC) already, so no API calls. --force asks again.

No changes to deliver.
```

The shipped brand, competitors and prompts are a public example, so the template shows real answers right away. Put in your own.

## Setup in three steps

1. **Use this template.** Click **Use this template** > **Create a new repository**. A private copy works the same.
2. **Add secrets.** In your new repo go to **Settings > Secrets and variables > Actions** and add:
   - `SCRAPEUNBLOCKER_KEY`: your API key ([get one here](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos)).
   - The Google Sheet (optional, but it's where the history lives):
     1. In the [Google Cloud console](https://console.cloud.google.com/), pick or create a project and enable the **Google Sheets API**.
     2. Under **IAM & Admin > Service Accounts**, create a service account, then **Keys > Add key > JSON**. A key file downloads.
     3. Open your Google Sheet, click **Share** and add the service account's email (`...@....iam.gserviceaccount.com`) as **Editor**.
     4. Add `GOOGLE_SHEET_ID` (the sheet's URL, or the id in it) and `GOOGLE_SERVICE_ACCOUNT_JSON` (the whole content of the key file). The tab (`Answers`) and its header row are created on the first run.
   - Where alerts and the digest go, any of:
     - `SLACK_WEBHOOK_URL`: a [Slack incoming webhook](https://api.slack.com/messaging/webhooks) for the channel.
     - `DISCORD_WEBHOOK_URL`: channel settings > Integrations > Webhooks.
     - `ALERT_WEBHOOK_URL`: any URL that takes a JSON POST (Zapier, Make, n8n, your own endpoint).
     - Email: `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD` and `EMAIL_TO` (comma-separated). Optional: `SMTP_PORT` (default 587 with STARTTLS; 465 uses SSL) and `EMAIL_FROM` (default: `SMTP_USERNAME`). For Gmail use `smtp.gmail.com` with an app password. By default email gets the weekly digest only; add `email` to `alerts.to` for change alerts too.
3. **Edit `config.yml`.** Put in your brand (its names and domains), your competitors and the questions your buyers ask, as they would type them.

Then open **Actions > AI visibility > Run workflow** to get the first check now instead of tomorrow morning. Tick **Dry run** to see the messages in the log without sending or saving anything.

Until `SCRAPEUNBLOCKER_KEY` is set, the scheduled workflow prints a notice and exits green without asking anything.

**Finding good prompts.** Try a question before you add it. This asks it once on each engine and shows how the answer names your brands. Nothing is saved (`--engine chatgpt` asks one engine only, `--show-answer` prints the answer):

```bash
ai-visibility-tracker ask "which issue tracker should a 10-person engineering team use"
```

### Run it on your own machine instead

```bash
git clone https://github.com/<you>/<your-copy>.git && cd <your-copy>
python -m pip install .
cp .env.example .env                     # then fill in the key and a destination
ai-visibility-tracker test-destinations  # a hello to each destination, creates the sheet tab
ai-visibility-tracker run --dry-run      # asks, prints what would be sent, saves nothing
ai-visibility-tracker run
```

For a cron job every morning:

```cron
23 7 * * * cd /path/to/your-copy && /path/to/venv/bin/ai-visibility-tracker run >> visibility.log 2>&1
```

Or with Docker, no local Python needed:

```bash
docker run --rm -v "$PWD":/app -w /app --env-file .env python:3.13-slim \
  sh -c "pip install -q . && ai-visibility-tracker run"
```

The `.env` file is read automatically, and real environment variables win. Locally, `GOOGLE_SERVICE_ACCOUNT_JSON` can also be the path of the key file. The state stays in `state/` in that folder.

## How it works

1. **Collect.** One call per prompt and engine through the official Python SDK: `client.chatgpt(prompt, country=...)`, `client.gemini(prompt, country=...)` and `client.google_ai_mode(prompt, proxy_country=..., hl=...)`. Each asks a signed-out session, so there's no memory or personalization, and each call starts a new conversation. Each returns the finished answer as Markdown plus the sites it cites or links. The three engines run side by side, and each asks your prompts in turn. In the test, a single answer took 8 to 21 seconds. A temporary error is retried once after 30 seconds. A prompt that still gets no answer is skipped and asked on the next run. A prompt the API refuses (too long, say) fails the run, because `config.yml` needs a fix.
2. **Process.**
   - **Read the answer.** Images and link targets are dropped, so only the text a reader sees counts. Your brand and each competitor are matched on their `name` and `aliases`, as whole words. Matching ignores case unless `match_case` is on, which you want for everyday words: "Linear" counts, "a linear workflow" doesn't. **Rank** is the order in which the tracked brands are first named, and **named before you** lists the competitors that come first. A competitor the prompt itself names is left out for that prompt. **Your site cited** means one of your `domains` (or a subdomain) is among the sites the answer cites or links: ChatGPT's source pills and links, Gemini's citations and sources, Google AI Mode's references and links. The **excerpt** is the line that first names you.
   - **What changed.** Each answer is compared with what your last message said about that prompt on that engine. That gives six kinds of change: named / no longer named, a competitor now named before you / you now named before a competitor, and your site now cited / no longer cited.
   - **Recheck.** Answers vary between identical calls. With `checks.recheck` on (the default), a change is asked a second time right away, and it's only sent when the second answer shows the same change. Otherwise the log says the answers disagree and nothing is sent.
   - **Weekly digest.** Built from the first answer of each check over the last 7 days, compared with the 7 days before. It covers the share of answers that name each brand (counting only answers where that brand was tracked), results by engine and by prompt, prompts that name competitors but not you, and the most cited sites.
3. **Deliver.** Every answer becomes a row in the Google Sheet. Rechecks are marked `recheck` in the *Check* column. A first check, or confirmed changes, go out as one message per run to the `alerts.to` destinations. The digest goes to `digest.to`. If no destination accepted a message, nothing is marked as told, so the next run sends it again without new API calls. Rows the Sheet didn't take are written on the next run. When you connect the Sheet later, the answers kept in the state file are written to it.
4. **State.** `state/visibility.json` holds one line per answer from the last `history_days` days, plus what you were last told per prompt and engine and the week of the last digest. The workflow commits it back to the repo when it changed. A prompt is asked at most once per UTC day, so a second run on the same day makes no API calls and sends nothing. To start fresh, delete the file. It's tied to the brand name, so a new brand needs a new file. One answer from the test run:

```json
{"round":"2026-11-17T19:30:04+00:00","at":"2026-11-17T19:30:23+00:00","day":"2026-11-17","prompt":"ef109a4cb6","engine":"chatgpt","sample":1,"named":true,"rank":1,"brands":{"Linear":1,"Jira":2,"GitHub Projects":3,"ClickUp":4},"ahead":[],"cited":true,"sites":["codetoolpilot.com","linear.app","atlassian.com","github.com","clickup.com","trello.com"],"excerpt":"For a small software development team (roughly 3–15 people), I'd recommend Linear as the best overall project management tool.","sheet":true}
```

**Good to know.** The engines answer signed out, from the country you set. A signed-in user with history can get a different answer. Signed-out ChatGPT shows which site backs a claim, but not the page URL. Rank is the order of mention, not a verdict, so read the excerpt to see how you're described. A single answer is one sample, which is why alerts wait for a second one and the digest gives shares over a week.

### Commands

| Command | What it does | API calls |
|---|---|---|
| `ai-visibility-tracker run` | Ask every prompt not asked today, log the answers to the Sheet, alert on confirmed changes, send the digest when it's due | prompts × engines, plus one per change |
| `ai-visibility-tracker run --dry-run` | Same, but print what each destination would get; send and save nothing | same as `run` |
| `ai-visibility-tracker run --force --engine gemini --prompt "issue tracker"` | Ask again today, only on these engines and prompts | 1 per prompt and engine, plus rechecks |
| `ai-visibility-tracker ask "<question>"` | Ask one question and show how each answer names your brands; saves nothing | 1 per engine |
| `ai-visibility-tracker digest` | Send this week's digest now (`--dry-run` prints it, `--force` sends it again) | 0 |
| `ai-visibility-tracker status` | The last answer per prompt and engine, and the last 7 days | 0 |
| `ai-visibility-tracker test-destinations` | A test message to each destination; creates the Sheet tab and header | 0 |

## Config reference

Everything lives in `config.yml`. Secrets never go in it.

| Key | Default | Meaning |
|---|---|---|
| `brand.name` | (required) | Your brand as answers name it. |
| `brand.aliases` | `[]` | Other names that count as your brand (`Linear.app`, `Acme Cloud`). |
| `brand.domains` | `[]` | Your sites. A cited or linked page on one of them (or a subdomain) is "your site cited". |
| `brand.match_case` | `false` | Match the names with their capitals only. Turn it on for everyday words. |
| `competitors` | `[]` | Up to 20 brands to rank against, each with the same `name`, `aliases`, `domains`, `match_case`. A plain name works too: `- Asana`. |
| `prompts` | (required) | The questions, as text, or `{prompt: ..., country: GB}` to ask one from another country. Up to 2,000 characters each. Changing a prompt's text or country makes it a new prompt. |
| `engines` | all three | `chatgpt`, `gemini`, `google_ai_mode`. |
| `country` | `US` | Two-letter country every prompt is asked from, unless it has its own. |
| `language` | `en` | The answer language for Google AI Mode (`de`, `pt-BR` ...). ChatGPT and Gemini answer in the language of the prompt. |
| `checks.recheck` | `true` | Confirm a change with a second answer before alerting. Costs one call per change found. |
| `checks.history_days` | `120` | Days of answers kept in the state file (14-730). |
| `alerts.to` | `[slack, discord, webhook]` | Where first checks and confirmed changes go. Any of `slack`, `discord`, `email`, `webhook`. `[]` turns alerts off. |
| `digest.day` | `monday` | The digest goes out on the first run on or after this day each week. `off` turns it off. |
| `digest.to` | `[slack, discord, email, webhook]` | Where the weekly digest goes. |
| `sheet.enabled` | `true` | Write one row per answer to the Google Sheet. |
| `sheet.tab` | `Answers` | The tab, created with a header row when missing. |
| `state` | `state/visibility.json` | The state file. |

A destination whose secrets aren't set is skipped. `test-destinations` lists what each one needs.

| Environment variable | Used for |
|---|---|
| `SCRAPEUNBLOCKER_KEY` | Your ScrapeUnblocker API key (required) |
| `GOOGLE_SHEET_ID` | The Google Sheet: its URL or id |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | The service account key: the JSON itself, or (locally) the path of the file |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook |
| `DISCORD_WEBHOOK_URL` | Discord channel webhook |
| `ALERT_WEBHOOK_URL` | Any URL that accepts a JSON POST |
| `SMTP_HOST`, `EMAIL_TO` | Email: the SMTP server and the recipients (comma-separated). Both are needed to send email. |
| `SMTP_PORT`, `SMTP_SECURITY` | Optional: port (default 587) and `starttls` (default), `ssl` (default on port 465) or `none` |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | SMTP login |
| `EMAIL_FROM` | Sender address (default: `SMTP_USERNAME`) |
| `GOOGLE_SHEETS_API_URL` | Only for tests against a local stand-in of the Sheets API |

## Cost

With the shipped `config.yml` (3 prompts on 3 engines), a run makes **9 API calls**, one per prompt and engine. On top of that, each answer that shows a change costs one recheck call, so 18 at most. The workflow runs once a day, which is about 270 calls a month plus rechecks. A second run on the same day makes no calls. To work out your own: prompts × engines per day, plus a few rechecks. A retry after a temporary error is one more call. `digest`, `status` and `test-destinations` make no API calls. `ask` makes one per engine.

## Adding another destination

A destination is a small class with `name`, `send`, `preview` and `test`, registered in `REGISTRY` in [`src/ai_visibility_tracker/sinks.py`](src/ai_visibility_tracker/sinks.py). Messages render themselves as Slack mrkdwn, Discord markdown, plain text, HTML or JSON (`messages.py`). Here is Google Chat as an example:

```python
class GoogleChatSink(ChatSink):
    """Google Chat incoming webhook."""

    name = "google_chat"
    style = messages.PLAIN

    def wrap(self, text: str) -> dict[str, Any]:
        return {"text": text}


REGISTRY["google_chat"] = SinkSpec(
    ("GOOGLE_CHAT_WEBHOOK_URL",),
    lambda env, http: GoogleChatSink(env["GOOGLE_CHAT_WEBHOOK_URL"].strip(), http),
)
```

Then add `"google_chat"` to `DESTINATIONS` in `config.py`, list it under `alerts.to` or `digest.to`, pass the secret in `.github/workflows/run.yml`, and add a test with the fake HTTP client in `tests/conftest.py`.

## Development

```bash
python -m pip install -e ".[dev]"
make lint     # ruff check + ruff format --check
make test     # offline tests; the SDK, webhooks, SMTP and the Sheets API are mocked, no API credit is used
```

The code is a small package in `src/ai_visibility_tracker/`:

- `collect.py`: the three engines via the SDK, with a retry, into one answer shape.
- `process.py`: reading an answer (named, rank, cited, excerpt), changes, the recheck, the weekly sums.
- `messages.py`: the change alert and the digest as Slack, Discord, plain text, HTML and JSON.
- `sinks.py`: Slack, Discord, email, the webhook and the Google Sheet (service account sign-in, tab and header setup, appends).
- `state.py`: the state file. `cli.py`: the command line.

## Links

- More ScrapeUnblocker automations: [google-rank-tracker](https://github.com/ScrapeUnblocker/google-rank-tracker) (daily Google positions, including AI Overview citations), [google-news-brief](https://github.com/ScrapeUnblocker/google-news-brief) (news on your brand and competitors) and [website-change-monitor](https://github.com/ScrapeUnblocker/website-change-monitor) (changes on competitor pricing pages).
- [ScrapeUnblocker](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos)
- [Documentation](https://docs.scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos)
- [API reference](https://docs.scrapeunblocker.com/api-reference?utm_source=github&utm_medium=integration&utm_campaign=example-repos)
- [Python SDK](https://docs.scrapeunblocker.com/sdks/python?utm_source=github&utm_medium=integration&utm_campaign=example-repos)

## License

[MIT](LICENSE). Copyright (c) 2026 ScrapeUnblocker.
