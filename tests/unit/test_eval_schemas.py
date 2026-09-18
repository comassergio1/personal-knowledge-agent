"""Unit tests for the evaluation request/response schemas (spec §31/§32)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.eval import (
    EvalCaseInput,
    EvalCaseResultRead,
    EvalMetricsRead,
    EvalRequest,
    EvalRunHistoryItem,
    EvalRunHistoryRead,
    EvalRunRead,
    EvalRunSummary,
    EvalThresholds,
)

_TS = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_case_input_defaults() -> None:
    case = EvalCaseInput(question="What is the WAN port?")

    assert case.name is None
    assert case.expected_facts == []
    assert case.adversarial is False
    assert case.project_id is None


def test_case_input_rejects_empty_question() -> None:
    with pytest.raises(ValidationError):
        EvalCaseInput(question="")
    with pytest.raises(ValidationError):
        EvalCaseInput()  # type: ignore[call-arg]


def test_case_input_accepts_full_payload() -> None:
    case = EvalCaseInput(
        name="wan-port",
        question="Which interface is the WAN?",
        expected_facts=["The WAN port is ether8."],
        adversarial=True,
        project_id="proj-1",
    )

    assert case.name == "wan-port"
    assert case.expected_facts == ["The WAN port is ether8."]
    assert case.adversarial is True
    assert case.project_id == "proj-1"


def test_request_defaults() -> None:
    request = EvalRequest(dataset=[EvalCaseInput(question="Q?")])

    assert request.top_k == 5
    assert request.project_id is None
    assert request.thresholds is None


def test_request_top_k_boundaries() -> None:
    assert EvalRequest(dataset=[EvalCaseInput(question="Q?")], top_k=1)
    assert EvalRequest(dataset=[EvalCaseInput(question="Q?")], top_k=15)
    with pytest.raises(ValidationError):
        EvalRequest(dataset=[EvalCaseInput(question="Q?")], top_k=0)
    with pytest.raises(ValidationError):
        EvalRequest(dataset=[EvalCaseInput(question="Q?")], top_k=16)


def test_request_rejects_empty_dataset() -> None:
    with pytest.raises(ValidationError):
        EvalRequest(dataset=[])  # type: ignore[list-item]


def test_thresholds_defaults_and_range() -> None:
    thresholds = EvalThresholds()

    assert thresholds.groundedness == 0.7
    assert thresholds.correctness == 0.5
    with pytest.raises(ValidationError):
        EvalThresholds(groundedness=-0.1)
    with pytest.raises(ValidationError):
        EvalThresholds(correctness=1.5)


def _metrics() -> EvalMetricsRead:
    return EvalMetricsRead(
        correctness=1.0,
        relevance=0.8,
        groundedness=0.9,
        hallucination_rate=0.0,
        source_quality=0.7,
        challenged_premise=False,
    )


def test_metrics_read_bounds() -> None:
    metrics = _metrics()

    assert metrics.correctness == 1.0
    with pytest.raises(ValidationError):
        EvalMetricsRead(
            correctness=1.1,
            relevance=0.5,
            groundedness=0.8,
            hallucination_rate=0.1,
            source_quality=0.4,
            challenged_premise=False,
        )


def test_run_read_structure() -> None:
    result = EvalCaseResultRead(
        case_name="wan-port",
        adversarial=False,
        question="Which interface is the WAN?",
        answer="ether8",
        sources=[{"title": "mikrotik", "score": 0.9}],
        metrics=_metrics(),
        verdict="pass",
        reason="meets thresholds",
    )
    run = EvalRunRead(
        summary=EvalRunSummary(total=1, passes=1, fails=0, errors=0),
        cases=[result],
    )

    assert run.summary.total == 1
    assert run.summary.passes == 1
    assert run.cases[0].verdict == "pass"
    assert run.cases[0].sources[0].title == "mikrotik"
    assert run.cases[0].metrics.groundedness == 0.9


def test_run_read_rejects_unknown_verdict() -> None:
    with pytest.raises(ValidationError):
        EvalCaseResultRead(
            case_name="x",
            adversarial=False,
            question="Q?",
            answer="A",
            sources=[],
            metrics=_metrics(),
            verdict="maybe",
            reason=None,
        )


def test_history_read_structure() -> None:
    history = EvalRunHistoryRead(
        items=[
            EvalRunHistoryItem(
                run_id="run-1",
                case_name="wan-port",
                verdict="pass",
                created_at=_TS,
                metrics={"groundedness": 0.9},
            )
        ]
    )

    assert history.items[0].run_id == "run-1"
    assert history.items[0].case_name == "wan-port"
    assert history.items[0].metrics == {"groundedness": 0.9}