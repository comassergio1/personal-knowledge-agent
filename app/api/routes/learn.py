"""Learning endpoints: the Phase 7 loop (learn/run, learn/reflect).

``run`` drives the learning loop (assess → research on demand → mode-aware
tutorial) through ``LearnService``; ``reflect`` turns a "¿qué aprendí?"
exchange into candidate memories through the memory extractor. Both reuse
the existing services — the loop never touches providers directly — and
surface infrastructure failures as ``LearnError`` → 502; schema validation
answers 422.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_learn_service
from app.schemas.learn import (
    LearnRequest,
    LearnResultRead,
    LearnSourceRead,
    ReflectRequest,
    ResearchRefRead,
    TutorialRefRead,
)
from app.schemas.memory import MemoryExtractResponse, MemoryRead
from app.services.learn_service import LearnError, LearnService

router = APIRouter(prefix="/learn", tags=["learn"])


@router.post(
    "/run", response_model=LearnResultRead, status_code=status.HTTP_201_CREATED
)
async def run_learning_loop(
    request: LearnRequest,
    learn_service: Annotated[LearnService, Depends(get_learn_service)],
) -> LearnResultRead:
    """Run assess → research on demand → generate, returning the tutorial.

    Empty goals are rejected by the schema (422); infrastructure failures
    inside the loop surface as 502 via ``LearnError``. The tutorial and (when
    it ran) the research report are persisted into the vault and indexed by
    the delegated services, exactly like their direct endpoints.
    """
    try:
        result = await learn_service.run(
            request.goal,
            mode=request.mode,
            project_id=request.project_id,
            title=request.title,
            allow_research=request.allow_research,
            research_threshold=request.research_threshold,
        )
    except LearnError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Learning loop failed: {exc}",
        ) from exc
    return LearnResultRead(
        goal=result.goal,
        mode=result.mode,
        needs_research=result.needs_research,
        research=(
            ResearchRefRead(
                document_id=result.research.document_id,
                file_path=result.research.file_path,
            )
            if result.research is not None
            else None
        ),
        tutorial=TutorialRefRead(
            document_id=result.tutorial.document_id,
            file_path=result.tutorial.file_path,
            content=result.tutorial.content,
            sources=[
                LearnSourceRead(title=source.title, score=source.score)
                for source in result.tutorial.sources
            ],
        ),
        reflect_hint=result.reflect_hint,
    )


@router.post(
    "/reflect",
    response_model=MemoryExtractResponse,
    status_code=status.HTTP_201_CREATED,
)
async def reflect_learning(
    request: ReflectRequest,
    learn_service: Annotated[LearnService, Depends(get_learn_service)],
) -> MemoryExtractResponse:
    """Turn a "¿qué aprendí?" exchange into candidate memories.

    The conversation is built by ``LearnService.reflect`` and handed to the
    memory extractor; the redacted candidates are persisted (status
    candidate) and returned. Empty goal/reflection are rejected by the schema
    (422); extractor failures surface as 502.
    """
    try:
        candidates = await learn_service.reflect(
            request.goal,
            request.what_i_learned,
            project_id=request.project_id,
        )
    except LearnError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Memory reflection failed: {exc}",
        ) from exc
    return MemoryExtractResponse(
        candidates=[MemoryRead.model_validate(candidate) for candidate in candidates]
    )