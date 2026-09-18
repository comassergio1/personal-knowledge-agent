"""Unit tests for EvalService: orchestration, error isolation, no-judge path.

The judge fake raises a plain ``RuntimeError`` (not ``LLMProviderError``) to
exercise the per-case error isolation: ``eval_metrics.judge`` deliberately
swallows provider errors into the heuristic fallback, so only real failures
(e.g. a programming error or a chat outage) reach the service's error path.
"""

from __future__ import annotations

import json

from app.core.config import Settings
from app.providers.llm.base import LLMResult
from app.repositories.eval_repository import EvalRepository
from app.schemas.chat import ChatResult, SourceRef
from app.schemas.eval import EvalCaseInput
from app.services.eval_service import EvalService

_EXCERPT = "El WAN del RB5009 está configurado en ether8."

_PASS_RUBRIC = {
    "correctness": 0.9,
    "relevance": 0.8,
    "groundedness": 0.8,
    "hallucination_claims": [],
    "challenged_premise": False,
}


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url="sqlite+aiosqlite:///:memory:",
    )


def _case(question: str = "¿En qué puerto está el WAN?", adversarial: bool = False) -> EvalCaseInput:
    return EvalCaseInput(
        name="wan-port" if not adversarial else "iot-premise",
        question=question,
        expected_facts=["ether8"] if not adversarial else ["VLAN 30"],
        adversarial=adversarial,
    )


class _FakeChatService:
    """Returns a canned grounded answer plus one source for every question."""

    def __init__(self, answer: str = "El WAN está en ether8.") -> None:
        self.answer = answer
        self.last_project_id: str | None = None
        self.last_top_k: int | None = None

    async def chat(
        self, message, *, top_k: int = 5, document_id: str | None = None, project_id: str | None = None
    ) -> ChatResult:
        self.last_top_k = top_k
        self.last_project_id = project_id
        return ChatResult(
            answer=self.answer,
            sources=[
                SourceRef(
                    document_id="doc-1",
                    title="VLAN Configuration",
                    chunk_index=0,
                    score=0.94,
                    excerpt=_EXCERPT,
                )
            ],
        )


class _FakeJudgeLLM:
    """Serves canned rubric JSON; can be armed to raise on a given call."""

    name = "fake-judge"

    def __init__(self, rubric: dict, *, raise_on_call: int | None = None) -> None:
        self.rubric = rubric
        self.raise_on_call = raise_on_call
        self.calls = 0

    async def generate(
        self, messages, *, model: str | None = None, **kwargs
    ) -> LLMResult:
        self.calls += 1
        if self.calls == self.raise_on_call:
            raise RuntimeError("judge exploded")
        return LLMResult(
            content=json.dumps(self.rubric),
            prompt_tokens=None,
            completion_tokens=None,
            provider="fake-judge",
            model="test-model",
        )


async def _run(
    db_session,
    *,
    chat=None,
    judge=None,
    dataset=None,
    **kwargs,
) -> tuple[EvalService, EvalRepository, object]:
    chat = chat if chat is not None else _FakeChatService()
    judge = judge if judge is not None else _FakeJudgeLLM(_PASS_RUBRIC)
    repository = EvalRepository(db_session)
    service = EvalService(chat, judge, repository, _settings())  # type: ignore[arg-type]
    result = await service.run(dataset or [_case()], **kwargs)
    return service, repository, result


# --- happy path ------------------------------------------------------------


async def test_run_normal_case_passes_and_persists(db_session) -> None:
    chat = _FakeChatService()
    _, repository, result = await _run(db_session, chat=chat)

    assert result.summary.total == 1
    assert result.summary.passes == 1
    assert result.summary.fails == 0
    assert result.summary.errors == 0
    assert result.judge == "llm"

    case = result.cases[0]
    assert case.case_name == "wan-port"
    assert case.adversarial is False
    assert case.answer == "El WAN está en ether8."
    assert [s.model_dump() for s in case.sources] == [
        {"title": "VLAN Configuration", "score": 0.94}
    ]
    assert case.metrics.correctness == 0.9  # judge wins over heuristics
    assert case.metrics.groundedness == 0.8
    assert case.metrics.source_quality == 0.94
    assert case.metrics.challenged_premise is False
    assert case.verdict == "pass"
    assert case.reason == "meets thresholds"

    # Chat received the run-level options.
    assert chat.last_top_k == 5
    assert chat.last_project_id is None

    # A case and a run row were persisted.
    cases = await repository.list_cases()
    assert [c.question for c in cases] == ["¿En qué puerto está el WAN?"]
    runs = await repository.list_runs()
    assert len(runs) == 1
    assert runs[0].verdict == "pass"
    assert runs[0].sources == [{"title": "VLAN Configuration", "score": 0.94}]
    assert runs[0].metrics["correctness"] == 0.9


async def test_run_forwards_project_id_and_top_k(db_session) -> None:
    chat = _FakeChatService()

    _, repository, _ = await _run(
        db_session, chat=chat, project_id="proj-1", top_k=3
    )

    assert chat.last_project_id == "proj-1"
    assert chat.last_top_k == 3
    case = (await repository.list_cases())[0]
    assert case.project_id == "proj-1"


# --- adversarial cases -----------------------------------------------------


async def test_run_adversarial_case_passes_when_premise_challenged(db_session) -> None:
    judge = _FakeJudgeLLM({**_PASS_RUBRIC, "challenged_premise": True})

    _, _, result = await _run(
        db_session, judge=judge, dataset=[_case(adversarial=True)]
    )

    case = result.cases[0]
    assert case.adversarial is True
    assert case.metrics.challenged_premise is True
    assert case.verdict == "pass"
    assert case.reason == "meets thresholds and challenges the premise"


async def test_run_adversarial_case_fails_without_challenged_premise(db_session) -> None:
    judge = _FakeJudgeLLM({**_PASS_RUBRIC, "challenged_premise": False})

    _, _, result = await _run(
        db_session, judge=judge, dataset=[_case(adversarial=True)]
    )

    case = result.cases[0]
    assert case.verdict == "fail"
    assert case.reason == "premise no desafiada"


# --- error isolation -------------------------------------------------------


async def test_run_judge_failure_marks_case_error_and_continues(db_session) -> None:
    judge = _FakeJudgeLLM(_PASS_RUBRIC, raise_on_call=2)
    dataset = [_case(), _case(question="¿Qué VLANs hay?", adversarial=True)]

    _, repository, result = await _run(db_session, judge=judge, dataset=dataset)

    assert result.summary.total == 2
    assert result.summary.passes == 1
    assert result.summary.errors == 1
    assert result.summary.fails == 0
    assert [case.verdict for case in result.cases] == ["pass", "error"]
    assert "judge exploded" in result.cases[1].reason
    assert result.cases[1].answer == ""
    assert result.cases[1].metrics.correctness == 0.0

    # Both runs (a pass and an error row) were persisted; the batch continued.
    runs = await repository.list_runs()
    assert {run.verdict for run in runs} == {"pass", "error"}
    error_run = next(run for run in runs if run.verdict == "error")
    assert error_run.metrics == {}
    assert judge.calls == 2


# --- no-judge path ---------------------------------------------------------


async def test_run_without_judge_uses_heuristics_and_never_raises(db_session) -> None:
    service = EvalService(_FakeChatService(), None, EvalRepository(db_session), _settings())

    result = await service.run([_case()])

    assert result.judge == "heuristics"
    case = result.cases[0]
    assert case.verdict == "pass"  # the fake answer covers ether8 in the excerpt
    assert case.metrics.correctness == 1.0
    assert case.metrics.relevance == 0.94
    assert case.metrics.challenged_premise is False


# --- history ---------------------------------------------------------------


async def test_history_lists_runs_with_case_names(db_session) -> None:
    service, _, _ = await _run(db_session)

    history = await service.history(limit=10)

    assert len(history.items) == 1
    item = history.items[0]
    assert item.case_name == "wan-port"
    assert item.verdict == "pass"
    assert item.metrics["correctness"] == 0.9
    assert item.run_id
    assert item.created_at is not None