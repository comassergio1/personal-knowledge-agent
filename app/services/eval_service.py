"""Eval orchestrator: run a dataset through chat + judge + metrics (spec §31/§32).

One :class:`EvalService` per app. ``run`` evaluates every case end to end:
grounded chat answer → LLM judge (with heuristic fallback) → metrics/verdict →
persist an ``EvalCase`` and an ``EvalRun``. A failing case is recorded with an
``error`` verdict and never aborts the batch; provider flakiness inside the
judge already degrades to heuristics without raising (``eval_metrics`` never
raises for LLM problems). Evaluations are knowledge-system health checks, not
memory: runs persist for history only and never pollute prompts or memories.
"""

from __future__ import annotations

from app.core.config import Settings
from app.core.logging import get_logger
from app.providers.llm.base import LLMProvider
from app.repositories.eval_repository import EvalRepository
from app.schemas.eval import (
    EvalCaseInput,
    EvalCaseResultRead,
    EvalMetricsRead,
    EvalRunHistoryItem,
    EvalRunHistoryRead,
    EvalRunRead,
    EvalRunSummary,
    EvalThresholds,
)
from app.services.chat_service import ChatService
from app.services.eval_metrics import compute_metrics, heuristic_eval, judge, verdict

_logger = get_logger("eval_service")

# Shown for a case that failed mid-run: the schema requires a full metrics
# object, and the persisted error row stores ``{}`` (see the model).
_EMPTY_METRICS_READ = EvalMetricsRead(
    correctness=0.0,
    relevance=0.0,
    groundedness=0.0,
    hallucination_rate=0.0,
    source_quality=0.0,
    challenged_premise=False,
)


class EvalService:
    """Runs evaluation datasets end to end and serves their history."""

    def __init__(
        self,
        chat: ChatService,
        judge_llm: LLMProvider | None,
        repository: EvalRepository,
        settings: Settings,
    ) -> None:
        self._chat = chat
        # ``None`` disables the judge: metrics then come from heuristics only
        # and the run result notes it (offline runs never raise on this).
        self._judge_llm = judge_llm
        self._repository = repository
        self._settings = settings

    async def run(
        self,
        dataset: list[EvalCaseInput],
        *,
        project_id: str | None = None,
        top_k: int = 5,
        thresholds: EvalThresholds | None = None,
    ) -> EvalRunRead:
        """Evaluate every case; a failing case never aborts the batch.

        Per case: persist an ``EvalCase`` from the input, chat for a grounded
        answer, ask the judge (unless disabled), merge judge metrics over the
        heuristic fallbacks, decide the verdict and persist an ``EvalRun``.
        Any exception inside one case is downgraded to an ``error`` row (the
        batch continues) with a short message as the reason.
        """
        summary = EvalRunSummary(total=len(dataset), passes=0, fails=0, errors=0)
        results: list[EvalCaseResultRead] = []
        judge_used = "llm" if self._judge_llm is not None else "heuristics"
        resolved_thresholds = thresholds or EvalThresholds()

        for case_input in dataset:
            case = await self._repository.create_case(
                question=case_input.question,
                name=case_input.name,
                expected_facts=case_input.expected_facts,
                adversarial=case_input.adversarial,
                project_id=case_input.project_id or project_id,
            )
            try:
                chat_result = await self._chat.chat(
                    case.question, top_k=top_k, project_id=project_id
                )
                answer = chat_result.answer
                excerpts = [source.excerpt for source in chat_result.sources]
                source_scores = [float(source.score) for source in chat_result.sources]
                response_sources = [
                    {"title": source.title, "score": float(source.score)}
                    for source in chat_result.sources
                ]
                judge_result = await self._judge(case, answer, excerpts)
                heuristics = heuristic_eval(
                    case.question,
                    case.expected_facts,
                    answer,
                    excerpts,
                    source_scores,
                    case.adversarial,
                )
                metrics = compute_metrics(
                    judge_result, heuristics, source_scores, case.adversarial
                )
                verdict_str, reason = verdict(
                    metrics, resolved_thresholds, case.adversarial
                )
                await self._repository.create_run(
                    case_id=case.id,
                    answer=answer,
                    sources=response_sources,
                    metrics=metrics,
                    verdict=verdict_str,
                )
                results.append(
                    EvalCaseResultRead(
                        case_name=case_input.name or case.question,
                        adversarial=case_input.adversarial,
                        question=case.question,
                        answer=answer,
                        sources=response_sources,
                        metrics=_metrics_read(metrics),
                        verdict=verdict_str,
                        reason=reason,
                    )
                )
                if verdict_str == "pass":
                    summary.passes += 1
                else:
                    summary.fails += 1
            # The per-case boundary is a deliberate blind catch: a failing
            # case must degrade to an ``error`` row and never abort the batch
            # (spec §31/§32).
            except Exception as exc:  # noqa: BLE001
                summary.errors += 1
                message = str(exc) or type(exc).__name__
                _logger.warning(
                    "eval case failed; recording an error run",
                    extra={"case": case.id, "error": message},
                )
                await self._persist_error_run(case.id, message)
                results.append(
                    EvalCaseResultRead(
                        case_name=case_input.name or case.question,
                        adversarial=case_input.adversarial,
                        question=case.question,
                        answer="",
                        sources=[],
                        metrics=_EMPTY_METRICS_READ,
                        verdict="error",
                        reason=message,
                    )
                )

        return EvalRunRead(summary=summary, cases=results, judge=judge_used)

    async def history(self, limit: int = 20) -> EvalRunHistoryRead:
        """Return the most recent runs with their case names (newest first)."""
        runs = await self._repository.list_runs(limit=limit)
        items: list[EvalRunHistoryItem] = []
        for run in runs:
            case = await self._repository.get_case(run.case_id)
            items.append(
                EvalRunHistoryItem(
                    run_id=run.id,
                    case_name=case.name if case and case.name else "",
                    verdict=run.verdict,
                    created_at=run.created_at,
                    metrics=dict(run.metrics or {}),
                )
            )
        return EvalRunHistoryRead(items=items)

    async def _judge(self, case, answer: str, excerpts: list[str]) -> dict:
        """One judge call, or ``{}`` (heuristics-only) when no judge is set."""
        if self._judge_llm is None:
            return {}
        return await judge(
            self._judge_llm,
            case.question,
            case.expected_facts,
            answer,
            excerpts,
            case.adversarial,
        )

    async def _persist_error_run(self, case_id: str, message: str) -> None:
        """Persist an ``error`` run row; a failure here is logged, not raised."""
        try:
            await self._repository.create_run(
                case_id=case_id,
                answer="",
                sources=[],
                metrics={},
                verdict="error",
            )
        # Persistence of the error row must not escape back into the batch.
        except Exception as exc:  # noqa: BLE001
            _logger.error(
                "eval error run could not be persisted",
                extra={"case": case_id, "error": str(exc) or type(exc).__name__},
            )


def _metrics_read(metrics: dict) -> EvalMetricsRead:
    """Project a computed metrics dict onto the response schema."""
    return EvalMetricsRead(
        correctness=metrics.get("correctness", 0.0),
        relevance=metrics.get("relevance", 0.0),
        groundedness=metrics.get("groundedness", 0.0),
        hallucination_rate=metrics.get("hallucination_rate", 0.0),
        source_quality=metrics.get("source_quality", 0.0),
        challenged_premise=bool(metrics.get("challenged_premise", False)),
    )