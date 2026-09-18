"""Unit tests for eval metrics + judge (fake LLM, lenient parsing, offline)."""

from __future__ import annotations

import json

import pytest

from app.providers.llm.base import LLMProviderError, LLMResult
from app.schemas.eval import EvalThresholds
from app.services.eval_metrics import (
    compute_metrics,
    heuristic_eval,
    judge,
    judge_prompt,
    verdict,
)


def _rubric() -> dict:
    return {
        "correctness": 0.9,
        "relevance": 0.7,
        "groundedness": 0.8,
        "hallucination_claims": ["claim one"],
        "challenged_premise": False,
    }


async def test_judge_parses_fenced_json() -> None:
    llm = FakeLLM("```json\n" + json.dumps(_rubric()) + "\n```")

    result = await judge(llm, "Q?", [], "A", [], adversarial=False)  # type: ignore[arg-type]

    assert result == _rubric()


async def test_judge_parses_plain_json() -> None:
    llm = FakeLLM(json.dumps(_rubric()))

    result = await judge(llm, "Q?", [], "A", [], adversarial=False)  # type: ignore[arg-type]

    assert result["correctness"] == 0.9
    assert result["hallucination_claims"] == ["claim one"]
    assert result["challenged_premise"] is False


class FakeLLM:
    """Returns a canned reply and records the messages it received."""

    name = "fake-eval-llm"

    def __init__(self, content: str) -> None:
        self.content = content
        self.messages: list | None = None

    async def generate(self, messages, *, model: str | None = None, **kwargs) -> LLMResult:
        self.messages = list(messages)
        return LLMResult(
            content=self.content,
            prompt_tokens=None,
            completion_tokens=None,
            provider="fake-eval-llm",
            model="test-model",
        )


class FailingLLM(FakeLLM):
    """Raises the provider error contract so the fallback can be exercised."""

    async def generate(self, messages, *, model: str | None = None, **kwargs) -> LLMResult:
        raise LLMProviderError("provider unreachable")


# --- judge parsing ---------------------------------------------------------


async def test_judge_returns_empty_on_broken_reply() -> None:
    llm = FakeLLM("I cannot evaluate that today, sorry.")

    result = await judge(llm, "Q?", [], "A", [], adversarial=False)  # type: ignore[arg-type]

    assert result == {}


async def test_judge_returns_empty_on_provider_error() -> None:
    result = await judge(FailingLLM(""), "Q?", [], "A", [], adversarial=False)  # type: ignore[arg-type]

    assert result == {}


async def test_judge_clamps_and_drops_unusable_fields() -> None:
    llm = FakeLLM(
        json.dumps(
            {
                "correctness": 1.5,
                "relevance": -0.3,
                "groundedness": "nope",
                "hallucination_claims": "not-a-list",
                "challenged_premise": "yes",
            }
        )
    )

    result = await judge(llm, "Q?", [], "A", [], adversarial=False)  # type: ignore[arg-type]

    assert result == {"correctness": 1.0, "relevance": 0.0}


async def test_judge_prompt_carries_adversarial_note() -> None:
    llm = FakeLLM(json.dumps(_rubric()))

    await judge(llm, "Q?", [], "A", [], adversarial=True)  # type: ignore[arg-type]

    user_content = llm.messages[1].content
    assert "adversarial case" in user_content
    assert "challenged_premise" in user_content


async def test_judge_prompt_is_plain_for_normal_cases() -> None:
    llm = FakeLLM(json.dumps(_rubric()))

    await judge(llm, "Q?", [], "A", [], adversarial=False)  # type: ignore[arg-type]

    assert "adversarial case" not in llm.messages[1].content


def test_judge_prompt_embeds_case_details() -> None:
    messages = judge_prompt(
        "Which port is the WAN?",
        ["The WAN port is ether8."],
        "The WAN port is ether8.",
        ["The WAN port is ether8 on the MikroTik."],
        adversarial=False,
    )

    assert messages[0].role == "system"
    user_content = messages[1].content
    assert "Which port is the WAN?" in user_content
    assert "The WAN port is ether8." in user_content
    assert "WAN port is ether8 on the MikroTik." in user_content


# --- heuristic fallbacks ---------------------------------------------------


def test_heuristic_correctness_coverts_expected_facts() -> None:
    ev = heuristic_eval("Q?", ["WAN ether8"], "The WAN port is ether8.", [], [0.9], False)

    assert ev["correctness"] == 1.0


def test_heuristic_correctness_is_partial_with_missing_facts() -> None:
    ev = heuristic_eval(
        "Q?", ["WAN ether8", "VLAN IoT"], "The WAN port is ether8.", [], [0.9], False
    )

    assert ev["correctness"] == 0.5


def test_heuristic_correctness_empty_facts_is_trivial() -> None:
    ev = heuristic_eval("Q?", [], "Anything at all.", [], [0.9], False)

    assert ev["correctness"] == 1.0


def test_heuristic_relevance_is_mean_of_source_scores() -> None:
    ev = heuristic_eval("Q?", [], "A", [], [0.8, 0.6, 0.7], False)

    assert ev["relevance"] == pytest.approx(0.7)


def test_heuristic_relevance_zero_without_scores() -> None:
    ev = heuristic_eval("Q?", [], "A", [], [], False)

    assert ev["relevance"] == 0.0


def test_heuristic_groundedness_and_claims() -> None:
    answer = "The WAN port is ether8. Zebras migrate during monsoon."
    sources = ["The WAN port is ether8 on the MikroTik."]

    ev = heuristic_eval("Q?", [], answer, sources, [0.9], False)

    assert ev["groundedness"] == pytest.approx(0.5)
    assert ev["hallucination_claims"] == ["Zebras migrate during monsoon."]


def test_heuristic_no_sources_grounds_nothing() -> None:
    ev = heuristic_eval("Q?", [], "The WAN port is ether8.", [], [], False)

    assert ev["groundedness"] == 0.0
    assert ev["hallucination_claims"] == ["The WAN port is ether8."]


def test_heuristic_never_infers_challenged_premise() -> None:
    ev = heuristic_eval("Q?", [], "A", [], [0.9], adversarial=True)

    assert ev["challenged_premise"] is False


# --- compute_metrics -------------------------------------------------------


def _heuristics(**overrides) -> dict:
    base = {
        "correctness": 0.4,
        "relevance": 0.3,
        "groundedness": 0.2,
        "hallucination_claims": ["h1", "h2"],
        "challenged_premise": False,
        "answer_sentence_count": 4,
    }
    base.update(overrides)
    return base


def test_compute_metrics_judge_wins_and_heuristics_fill_gaps() -> None:
    judge_result = {"correctness": 1.0, "groundedness": 0.9, "challenged_premise": True}

    metrics = compute_metrics(judge_result, _heuristics(), [0.8, 0.6], adversarial=True)

    assert metrics["correctness"] == 1.0
    assert metrics["groundedness"] == 0.9
    assert metrics["relevance"] == 0.3  # judge did not return it
    assert metrics["hallucination_claims"] == ["h1", "h2"]
    assert metrics["hallucination_rate"] == 0.5
    assert metrics["source_quality"] == pytest.approx(0.7)
    assert metrics["challenged_premise"] is True


def test_compute_metrics_empty_judge_falls_back_fully() -> None:
    metrics = compute_metrics({}, _heuristics(), [], adversarial=False)

    assert metrics["correctness"] == 0.4
    assert metrics["relevance"] == 0.3
    assert metrics["groundedness"] == 0.2
    assert metrics["hallucination_rate"] == 0.5
    assert metrics["source_quality"] == 0.0
    assert metrics["challenged_premise"] is False


def test_compute_metrics_judge_claims_override_heuristics() -> None:
    judge_result = {"hallucination_claims": ["j1"]}

    metrics = compute_metrics(judge_result, _heuristics(), [], adversarial=False)

    assert metrics["hallucination_claims"] == ["j1"]
    assert metrics["hallucination_rate"] == 0.25


# --- verdict ---------------------------------------------------------------


def test_verdict_passes_above_default_thresholds() -> None:
    result, reason = verdict(
        {"groundedness": 0.8, "correctness": 0.7}, None, adversarial=False
    )

    assert result == "pass"
    assert reason


def test_verdict_fails_on_low_groundedness() -> None:
    result, reason = verdict(
        {"groundedness": 0.3, "correctness": 0.9}, None, adversarial=False
    )

    assert result == "fail"
    assert "groundedness" in reason
    assert "correctness" not in reason


def test_verdict_fails_on_low_correctness() -> None:
    result, reason = verdict(
        {"groundedness": 0.9, "correctness": 0.2}, None, adversarial=False
    )

    assert result == "fail"
    assert "correctness" in reason


def test_verdict_reports_every_failing_dimension() -> None:
    result, reason = verdict(
        {"groundedness": 0.1, "correctness": 0.1}, None, adversarial=False
    )

    assert result == "fail"
    assert "groundedness" in reason
    assert "correctness" in reason


def test_verdict_adversarial_fails_without_challenged_premise() -> None:
    result, reason = verdict(
        {"groundedness": 0.9, "correctness": 0.8, "challenged_premise": False},
        None,
        adversarial=True,
    )

    assert result == "fail"
    assert reason == "premise no desafiada"


def test_verdict_adversarial_passes_when_premise_challenged() -> None:
    result, _ = verdict(
        {"groundedness": 0.9, "correctness": 0.8, "challenged_premise": True},
        None,
        adversarial=True,
    )

    assert result == "pass"


def test_verdict_thresholds_override_defaults() -> None:
    strict = EvalThresholds(groundedness=0.95, correctness=0.9)

    result, reason = verdict(
        {"groundedness": 0.9, "correctness": 0.85}, strict, adversarial=False
    )

    assert result == "fail"
    assert "groundedness" in reason
    assert "correctness" in reason