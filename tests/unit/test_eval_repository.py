"""Unit tests for EvalRepository over in-memory SQLite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.repositories.eval_repository import EvalRepository

_BASE = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


async def test_create_case_persists_defaults(db_session) -> None:
    repo = EvalRepository(db_session)

    case = await repo.create_case(question="What is the WAN port?")

    assert len(case.id) == 36
    assert case.name is None
    assert case.question == "What is the WAN port?"
    assert case.expected_facts == []
    assert case.adversarial is False
    assert case.project_id is None
    assert case.created_at is not None


async def test_create_case_persists_full_payload(db_session) -> None:
    repo = EvalRepository(db_session)

    case = await repo.create_case(
        name="wan-port",
        question="Which interface is the WAN?",
        expected_facts=("The WAN port is ether8.",),
        adversarial=True,
        project_id="proj-1",
    )

    assert case.name == "wan-port"
    assert case.expected_facts == ["The WAN port is ether8."]
    assert case.adversarial is True
    assert case.project_id == "proj-1"


async def test_get_case_returns_one_or_none(db_session) -> None:
    repo = EvalRepository(db_session)
    created = await repo.create_case(question="Which interface is the WAN?")

    fetched = await repo.get_case(created.id)

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.question == "Which interface is the WAN?"
    assert await repo.get_case("missing-id") is None


async def test_list_cases_returns_newest_first(db_session) -> None:
    repo = EvalRepository(db_session)
    cases = []
    for day in (1, 2, 3):
        case = await repo.create_case(question=f"Question {day}")
        case.created_at = _BASE + timedelta(days=day)
        await db_session.commit()
        cases.append(case)

    listed = await repo.list_cases()

    assert [c.id for c in listed] == [cases[2].id, cases[1].id, cases[0].id]


async def test_create_run_persists_metrics_sources_and_verdict(db_session) -> None:
    repo = EvalRepository(db_session)
    case = await repo.create_case(question="What is the WAN port?")

    run = await repo.create_run(
        case_id=case.id,
        answer="ether8",
        sources=[{"title": "mikrotik", "content": "excerpt", "score": 0.9}],
        metrics={"groundedness": 0.8, "correctness": 1.0},
        verdict="pass",
    )

    assert len(run.id) == 36
    assert run.case_id == case.id
    assert run.answer == "ether8"
    assert run.sources == [{"title": "mikrotik", "content": "excerpt", "score": 0.9}]
    assert run.metrics == {"groundedness": 0.8, "correctness": 1.0}
    assert run.verdict == "pass"
    assert run.created_at is not None


async def test_list_runs_returns_newest_first(db_session) -> None:
    repo = EvalRepository(db_session)
    case = await repo.create_case(question="What is the WAN port?")
    runs = []
    for day in (1, 2, 3):
        run = await repo.create_run(case_id=case.id, answer=f"answer {day}", verdict="pass")
        run.created_at = _BASE + timedelta(days=day)
        await db_session.commit()
        runs.append(run)

    listed = await repo.list_runs()

    assert [r.id for r in listed] == [runs[2].id, runs[1].id, runs[0].id]
    assert listed[0].created_at == _BASE + timedelta(days=3)


async def test_list_runs_caps_at_limit(db_session) -> None:
    repo = EvalRepository(db_session)
    case = await repo.create_case(question="What is the WAN port?")
    runs = []
    for day in (1, 2, 3):
        run = await repo.create_run(case_id=case.id, answer=f"answer {day}", verdict="pass")
        run.created_at = _BASE + timedelta(days=day)
        await db_session.commit()
        runs.append(run)

    listed = await repo.list_runs(limit=2)

    assert [r.id for r in listed] == [runs[2].id, runs[1].id]