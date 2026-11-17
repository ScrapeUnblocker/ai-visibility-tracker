"""ai-visibility-tracker: is your brand named when people ask AI assistants your prompts?

Each run asks ChatGPT, Gemini and Google AI Mode every prompt in ``config.yml`` (once per
day) through the ScrapeUnblocker API, reads each answer for your brand and your
competitors (named or not, in which order, which sites are cited), logs every answer to a
Google Sheet, and alerts Slack, Discord, email or a webhook only when your visibility
changes, after a second answer confirms it. A weekly digest sums up the share of answers
that name each brand. A state file remembers what you were told.

    from ai_visibility_tracker import load_config, ask, read_answer
"""

from .collect import Answer, AskError, ask
from .config import Brand, Config, ConfigError, Prompt, load_config
from .messages import Alert, DigestMessage, build_alert, build_digest, render_plain
from .process import Change, Check, Seen, changes, confirmed, read_answer, weekly
from .state import State

__version__ = "0.1.0"

__all__ = [
    "Alert",
    "Answer",
    "AskError",
    "Brand",
    "Change",
    "Check",
    "Config",
    "ConfigError",
    "DigestMessage",
    "Prompt",
    "Seen",
    "State",
    "__version__",
    "ask",
    "build_alert",
    "build_digest",
    "changes",
    "confirmed",
    "load_config",
    "read_answer",
    "render_plain",
    "weekly",
]
