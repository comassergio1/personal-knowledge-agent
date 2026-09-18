"""Eval metrics + LLM judge (spec §31/§32), offline-first.

The judge is one ``generate()`` call per case with a strict rubric demanding
a JSON object; the reply is parsed leniently (same spirit as the memory
extractor) and any unusable reply falls back to ``{}`` so callers use the
pure heuristic helpers instead — this module never raises for LLM flakiness.

The heuristic fallbacks are pure token/word-overlap arithmetic: fast, offline
and unit-testable, but deliberately conservative. ``challenged_premise``
cannot be inferred heuristically, so adversarial verdicts only pass when the
judge itself reports that the answer challenged the premise.
"""

from __future__ import annotations

import json
import math
import re

from app.core.logging import get_logger
from app.providers.llm.base import ChatMessage, LLMProvider, LLMProviderError
from app.schemas.eval import EvalThresholds

# A claim sentence whose source word-overlap falls below this ratio is
# considered unsupported (a hallucination claim) in the heuristics.
_HALLUCINATION_OVERLAP_THRESHOLD = 0.5

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD_RE = re.compile(r"\w+", re.UNICODE)

# Strips ```json ... ``` fences (with or without the language tag).
_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")

# Stable marker identifying the judge system prompt. The testing fake LLM in
# ``app.main`` keys off it to answer judge calls with canned rubric JSON; it
# must remain a substring of ``_JUDGE_SYSTEM_PROMPT`` below.
JUDGE_PROMPT_MARKER = (
    "You are a strict evaluator of assistant answers for a personal knowledge agent"
)

_JUDGE_SYSTEM_PROMPT = (
    "You are a strict evaluator of assistant answers for a personal knowledge "
    "agent. You receive a question, the expected facts the answer must cover, "
    "the assistant's answer, and the source excerpts the answer was grounded "
    "on. Return ONLY a strict JSON object with this exact shape:\n"
    '{"correctness": 0..1, "relevance": 0..1, "groundedness": 0..1, '
    '"hallucination_claims": ["..."], "challenged_premise": true|false}\n'
    "Semantics:\n"
    "- correctness: the fraction of the expected facts that the answer covers (0..1).\n"
    "- relevance: how on-topic the answer is for the question (0..1).\n"
    "- groundedness: whether every claim in the answer is supported by the "
    "provided source excerpts (0..1).\n"
    "- hallucination_claims: a list of answer claims that are NOT supported by "
    "the sources (an empty list when there are none).\n"
    "- challenged_premise: whether the answer explicitly disputes or rejects "
    "the premise stated in the question. Set it true only when the answer "
    "clearly contradicts or calls out a premise; otherwise false.\n"
    "Return no other text."
)

_ADVERSARIAL_NOTE = (
    "\nIMPORTANT: this is an adversarial case. The question may embed a false "
    "premise on purpose. Set challenged_premise to true if (and only if) the "
    "answer explicitly disputes or rejects that premise; a silent or agreeable "
    "answer must set it to false."
)

_logger = get_logger("eval_metrics")


def judge_prompt(
    question: str,
    expected_facts: list[str],
    answer: str,
    sources_excerpts: list[str],
    adversarial: bool,
) -> list[ChatMessage]:
    """Render the rubric chat for one case: system persona + user details."""
    lines = [f"Question: {question}", ""]
    if expected_facts:
        lines.append("Expected facts the answer must cover:")
        lines.extend(f"- {fact}" for fact in expected_facts)
        lines.append("")
    lines.append(f"Answer: {answer}")
    lines.append("")
    if sources_excerpts:
        lines.append("Source excerpts the answer was grounded on:")
        lines.extend(f"{i}. {excerpt}" for i, excerpt in enumerate(sources_excerpts, 1))
    else:
        lines.append("Source excerpts: (none)")
    if adversarial:
        lines.append(_ADVERSARIAL_NOTE)
    return [
        ChatMessage(role="system", content=_JUDGE_SYSTEM_PROMPT),
        ChatMessage(role="user", content="\n".join(lines)),
    ]


async def judge(
    llm: LLMProvider,
    question: str,
    expected_facts: list[str],
    answer: str,
    sources_excerpts: list[str],
    adversarial: bool,
) -> dict:
    """One judge call; returns the rubric dict or ``{}`` when unusable.

    Never raises for provider or parse failures — the caller falls back to
    ``heuristic_eval``. Only real programming errors may surface.
    """
    messages = judge_prompt(
        question, expected_facts, answer, sources_excerpts, adversarial
    )
    try:
        result = await llm.generate(messages=messages, model=None)
    except LLMProviderError as exc:
        _logger.warning(
            "eval judge call failed; falling back to heuristics",
            extra={"llm": getattr(llm, "name", "unknown"), "error": str(exc)},
        )
        return {}
    parsed = _parse_judge_result(result.content)
    if not parsed:
        _logger.warning("eval judge reply was not usable JSON; falling back to heuristics")
    return parsed


def heuristic_eval(
    question: str,
    expected_facts: list[str],
    answer: str,
    sources_excerpts: list[str],
    source_scores: list[float],
    adversarial: bool,
) -> dict:
    """Pure offline fallback metrics via token/word overlap.

    ``challenged_premise`` cannot be inferred heuristically, so it is always
    False here (adversarial verdicts then fail unless the judge reports the
    premise was challenged).
    """
    sentences = _sentences(answer)
    source_words = set(_words(" ".join(sources_excerpts)))
    correctness = _token_containment(expected_facts, answer)
    relevance = _mean(source_scores) if source_scores else 0.0
    if sentences:
        overlaps = [(_overlap(_words(s), source_words), s) for s in sentences]
        groundedness = sum(o for o, _ in overlaps) / len(overlaps)
        claims = [s for o, s in overlaps if o < _HALLUCINATION_OVERLAP_THRESHOLD]
    else:
        groundedness = 0.0
        claims = []
    return {
        "correctness": correctness,
        "relevance": relevance,
        "groundedness": groundedness,
        "hallucination_claims": claims,
        "challenged_premise": False,
        # Internal carrier so ``compute_metrics`` can derive the rate; not a
        # metric itself.
        "answer_sentence_count": len(sentences),
    }


def compute_metrics(
    judge_result: dict,
    heuristics: dict,
    source_scores: list[float],
    adversarial: bool,
) -> dict:
    """Merge judge values over heuristic fallbacks into the full metric dict.

    Judge wins for every value it returned; heuristics fill the gaps.
    ``hallucination_rate`` is the share of answer sentences that are
    unsupported claims; ``source_quality`` is the mean retrieval score.
    """
    judge_result = judge_result or {}
    merged: dict = {}
    for key in ("correctness", "relevance", "groundedness"):
        judge_value = _clamp_float(judge_result.get(key))
        merged[key] = judge_value if judge_value is not None else heuristics[key]
    claims = judge_result.get("hallucination_claims")
    if isinstance(claims, list):
        claims = [str(c) for c in claims if str(c).strip()]
    else:
        claims = heuristics.get("hallucination_claims", [])
    challenged = judge_result.get("challenged_premise")
    if not isinstance(challenged, bool):
        challenged = heuristics.get("challenged_premise", False)
    sentence_count = heuristics.get("answer_sentence_count") or 1
    hallucination_rate = len(claims) / sentence_count if claims else 0.0
    hallucination_rate = min(1.0, hallucination_rate)
    return {
        "correctness": merged["correctness"],
        "relevance": merged["relevance"],
        "groundedness": merged["groundedness"],
        "hallucination_claims": claims,
        "hallucination_rate": hallucination_rate,
        "source_quality": _mean(source_scores) if source_scores else 0.0,
        "challenged_premise": challenged,
    }


def verdict(metrics: dict, thresholds: EvalThresholds | None, adversarial: bool) -> tuple[str, str]:
    """Decide the verdict for one case: ``("pass"|"fail", reason)``.

    Pass requires groundedness and correctness at/above their thresholds;
    adversarial cases additionally require ``challenged_premise`` to be True.
    """
    resolved = thresholds or EvalThresholds()
    groundedness = metrics.get("groundedness", 0.0)
    correctness = metrics.get("correctness", 0.0)
    reasons: list[str] = []
    if groundedness < resolved.groundedness:
        reasons.append(
            f"groundedness {groundedness:.2f} below threshold {resolved.groundedness:.2f}"
        )
    if correctness < resolved.correctness:
        reasons.append(
            f"correctness {correctness:.2f} below threshold {resolved.correctness:.2f}"
        )
    if adversarial and not metrics.get("challenged_premise", False):
        reasons.append("premise no desafiada")
    if reasons:
        return ("fail", "; ".join(reasons))
    if adversarial:
        return ("pass", "meets thresholds and challenges the premise")
    return ("pass", "meets thresholds")


# --- pure helpers ----------------------------------------------------------


def _words(text: str) -> list[str]:
    """Lowercased word tokens of ``text`` (unicode-aware)."""
    return _WORD_RE.findall(text.lower())


def _sentences(text: str) -> list[str]:
    """Split ``text`` into non-empty sentences on punctuation/newlines."""
    parts = _SENTENCE_SPLIT_RE.split(text.strip())
    return [part.strip() for part in parts if part.strip()]


def _token_containment(expected_facts: list[str], answer: str) -> float:
    """Fraction of expected-fact tokens present in the answer (0..1)."""
    answer_words = set(_words(answer))
    total = 0
    covered = 0
    for fact in expected_facts:
        fact_words = _words(fact)
        if not fact_words:
            continue
        total += len(fact_words)
        covered += sum(1 for word in fact_words if word in answer_words)
    # No expected facts means nothing to cover: trivially satisfied.
    return covered / total if total else 1.0


def _overlap(words: list[str], source_words: set[str]) -> float:
    """Fraction of the sentence words present in the source vocabulary."""
    if not words:
        return 0.0
    return sum(1 for word in words if word in source_words) / len(words)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _clamp_float(value) -> float | None:
    """``float(value)`` clamped to [0, 1]; None when not a usable number."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):  # NaN / infinity are unusable
        return None
    return max(0.0, min(1.0, number))


def _parse_judge_result(raw: str) -> dict:
    """Leniently parse an LLM reply into a validated rubric dict.

    Fences are stripped, the first ``{`` to last ``}`` substring is parsed and
    every field is type-checked/clamped; anything unusable yields ``{}``.
    """
    text = _FENCE_RE.sub("", raw).strip()
    obj = _extract_json_object(text)
    if not isinstance(obj, dict):
        return {}
    cleaned: dict = {}
    for key in ("correctness", "relevance", "groundedness"):
        value = _clamp_float(obj.get(key))
        if value is not None:
            cleaned[key] = value
    claims = obj.get("hallucination_claims")
    if isinstance(claims, list):
        cleaned["hallucination_claims"] = [str(c) for c in claims if str(c).strip()]
    if isinstance(obj.get("challenged_premise"), bool):
        cleaned["challenged_premise"] = obj["challenged_premise"]
    return cleaned


def _extract_json_object(text: str):
    """``json.loads`` the substring between the first ``{`` and last ``}``.

    Returns None when either delimiter is missing or the substring does not
    parse; lenient by design because LLM JSON output is unreliable.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except (json.JSONDecodeError, TypeError, ValueError):
        return None