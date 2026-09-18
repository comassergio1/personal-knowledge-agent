"""Research-intent detection for the OpenAI-compatible chat shim (spec §19).

A v1 heuristic: the last user message triggers the research flow when any
curated, case-insensitive substring pattern matches. Intent classification is
deliberately shallow — no LLM, no grammar — and the coarse patterns carry
documented false-positive risk:

- **``en la web`` / ``en internet``** are matched anywhere in the message, so
  "¿qué dice mi nota en internet?" (about a note's content, not about
  searching the web) triggers research. Acceptable for v1: the length cap
  keeps research inputs bounded, and the shim always answers honestly — a
  research run the user did not want still returns a real report, never a
  fake one.
- **``investiga`` / ``research``** are substring triggers, so derived forms
  ("investigación", "investigamos", "researched", "researchers") also match.
- The English phrases ("look up on the web", "search the web") are matched
  verbatim after whitespace collapsing, so stray casing or spacing never
  matters, but rewordings are missed (no stemming); a miss falls back to the
  normal grounded chat, which is safe.

The message length cap (``RESEARCH_MAX_LENGTH``) bounds the research input:
messages longer than the cap never trigger, whatever they contain.
"""

from __future__ import annotations

import re

RESEARCH_MAX_LENGTH = 400

# Case-insensitive substring triggers (English + Spanish, the product's two
# chat languages); coarse on purpose, see the module docstring.
RESEARCH_TRIGGERS: tuple[str, ...] = (
    "investigá",
    "investiga",
    "investigar en la web",
    "buscá fuentes",
    "busca fuentes",
    "buscá en la web",
    "busca en la web",
    "buscá en internet",
    "busca en internet",
    "buscar en internet",
    "en la web",
    "en internet",
    "research",
    "look up on the web",
    "search the web",
)

# Any run of whitespace collapses to one space, so "buscá   en   la web"
# matches "buscá en la web" after normalization.
_WHITESPACE_RE = re.compile(r"\s+")


def is_research_request(message: str) -> bool:
    """Return True when ``message`` asks for web research (v1 heuristic).

    The raw message length is checked first: no trigger can fire on a message
    longer than ``RESEARCH_MAX_LENGTH``, even when whitespace collapsing would
    shorten it. Otherwise the message is lowercased and its whitespace
    collapsed, then matched against every trigger as a substring.
    """
    if len(message) > RESEARCH_MAX_LENGTH:
        return False
    normalized = _WHITESPACE_RE.sub(" ", message).lower()
    return any(trigger in normalized for trigger in RESEARCH_TRIGGERS)