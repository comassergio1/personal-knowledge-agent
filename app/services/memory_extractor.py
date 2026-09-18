"""LLM-driven memory extraction from a conversation (spec §13 flow).

The extractor is a thin, provider-agnostic wrapper: it renders a conversation
into a hardcoded prompt (no template files), asks the configured LLM for a
JSON array of candidate memories, and leniently parses the reply — LLM JSON
is unreliable, so code fences are stripped, the first ``[``/last ``]`` pair is
located, and a single-object fallback is attempted before giving up.

Candidates returned here are raw (NOT yet redacted); ``MemoryService`` applies
secret redaction right before persisting (spec §34), so secrets never reach
the database or the vector store.
"""

from __future__ import annotations

import json
import re

from app.core.logging import get_logger
from app.domain.models.memory import MEMORY_TYPES
from app.providers.llm.base import ChatMessage, LLMProvider, LLMProviderError
from app.schemas.memory import ConversationTurn

_SYSTEM_PROMPT = (
    "You are a personal memory extraction assistant. Extract durable, factual "
    "personal memories from the conversation. Types: semantic (general "
    "knowledge), episodic (things we did or experienced), procedural (how-to "
    "steps), preference (persistent user preferences). Output ONLY a JSON "
    "array of objects with keys type, content, confidence (0..1); never output "
    "secrets, code, or keys. Return no other text."
)

_USER_SUFFIX = (
    "\n\nReturn ONLY the JSON array of extracted memories, with no other text "
    "or explanation."
)

# Strips ```json ... ``` fences (with or without the language tag).
_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


class MemoryExtractionError(Exception):
    """Raised when the LLM extraction call itself fails (routes map to 502)."""


class MemoryExtractor:
    """Turns a conversation into candidate memory dicts via the LLM gateway."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm
        self._logger = get_logger("memory_extractor")

    async def extract(self, conversation: list[ConversationTurn]) -> list[dict]:
        """Return candidate dicts ``{"type", "content", "confidence", "source"?}``.

        Candidates are unredacted here; an unusable reply yields ``[]`` instead
        of raising (the caller still gets a warning in the logs).
        """
        rendered = "\n".join(f"{turn.role}: {turn.content}" for turn in conversation)
        messages = [
            ChatMessage(role="system", content=_SYSTEM_PROMPT),
            ChatMessage(role="user", content=f"{rendered}{_USER_SUFFIX}"),
        ]
        try:
            result = await self._llm.generate(messages=messages, model=None)
        except LLMProviderError as exc:
            raise MemoryExtractionError(f"memory extraction failed: {exc}") from exc
        candidates = self._parse_result(result.content)
        if not candidates:
            self._logger.warning(
                "llm returned no usable memory candidates",
                extra={"llm": self._llm.name},
            )
        return candidates

    def _parse_result(self, raw: str) -> list[dict]:
        """Leniently parse an LLM reply into cleaned candidate dicts."""
        text = _FENCE_RE.sub("", raw).strip()
        return self._clean(_as_list(text))

    def _clean(self, items: list) -> list[dict]:
        """Keep only valid candidate dicts with well-formed, clamped fields."""
        cleaned: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            memory_type = item.get("type")
            content = item.get("content")
            if memory_type not in MEMORY_TYPES:
                continue
            if not isinstance(content, str) or not content.strip():
                continue
            try:
                confidence = float(item.get("confidence", 0.5))
            except (TypeError, ValueError):
                confidence = 0.5
            candidate: dict = {
                "type": memory_type,
                "content": content,
                "confidence": max(0.0, min(1.0, confidence)),
            }
            source = item.get("source")
            if isinstance(source, str) and source.strip():
                candidate["source"] = source
            cleaned.append(candidate)
        return cleaned


def _as_list(text: str) -> list:
    """Return the first array, or failing that a single object, as a list.

    ``None`` (or ``[]``) comes back when the reply holds no parseable JSON.
    """
    items = _extract_json(text, "[", "]")
    if items is not None and isinstance(items, list):
        return items
    single = _extract_json(text, "{", "}")
    if single is not None:
        return [single]
    return []


def _extract_json(text: str, open_char: str, close_char: str):
    """``json.loads`` the substring between the first and last delimiter.

    Returns None when either delimiter is missing or the substring does not
    parse; lenient by design because LLM JSON output is unreliable.
    """
    start = text.find(open_char)
    end = text.rfind(close_char)
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except (json.JSONDecodeError, TypeError, ValueError):
        return None