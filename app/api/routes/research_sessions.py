"""Research-session endpoints: sessions, turns, and save-as-tutorial.

The "Explorar" console tab is the primary consumer: create/list/resume
sessions, send turns (research on demand via the curated triggers, grounded
answers otherwise), and save the session's topic as a tutorial. The router
lives under ``/research/sessions`` and never shadows the existing
``/research/run`` endpoint: both paths are exact and disjoint.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_research_chat_service
from app.api.routes.research import _SEARCH_UNAVAILABLE
from app.domain.models.research_session import ResearchSession, ResearchTurn
from app.providers.llm.base import LLMProviderError
from app.schemas.research_session import (
    ResearchSessionCreate,
    ResearchSessionDetail,
    ResearchSessionList,
    ResearchSessionRead,
    ResearchTurnRead,
    ResearchTurnRequest,
    ResearchTutorialRequest,
)
from app.schemas.tutorial import TutorialRead, TutorialSourceRead
from app.services.research_chat_service import (
    ResearchChatService,
    SearchUnavailableError,
    SessionNotFoundError,
)
from app.services.research_service import ResearchError

router = APIRouter(prefix="/research/sessions", tags=["research sessions"])


def _session_read(session: ResearchSession, turn_count: int) -> ResearchSessionRead:
    """Map a session row to its API shape."""
    return ResearchSessionRead(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        turn_count=turn_count,
    )


def _turn_read(turn: ResearchTurn) -> ResearchTurnRead:
    """Map a turn row to its API shape."""
    return ResearchTurnRead(
        id=turn.id,
        session_id=turn.session_id,
        role=turn.role,
        content=turn.content,
        kind=turn.kind,
        research_document_id=turn.research_document_id,
        sources=turn.sources,
        created_at=turn.created_at,
    )


@router.post("", response_model=ResearchSessionRead, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: ResearchSessionCreate,
    service: Annotated[ResearchChatService, Depends(get_research_chat_service)],
) -> ResearchSessionRead:
    """Create a research session; a missing title gets the Spanish default."""
    session = await service.create_session(payload.title)
    return _session_read(session, turn_count=0)


@router.get("", response_model=ResearchSessionList)
async def list_sessions(
    service: Annotated[ResearchChatService, Depends(get_research_chat_service)],
) -> ResearchSessionList:
    """Return sessions ordered by most recent activity, with turn counts.

    Old sessions stay listed so the console can resume them after a refresh.
    """
    rows = await service.list_sessions()
    return ResearchSessionList(
        items=[_session_read(session, count) for session, count in rows],
        total=len(rows),
    )


@router.get("/{session_id}", response_model=ResearchSessionDetail)
async def get_session(
    session_id: str,
    service: Annotated[ResearchChatService, Depends(get_research_chat_service)],
) -> ResearchSessionDetail:
    """Return one session with its full thread; 404 when it is missing."""
    session = await service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Research session not found")
    turns = await service.turns(session_id)
    return ResearchSessionDetail(
        **_session_read(session, turn_count=len(turns)).model_dump(),
        turns=[_turn_read(turn) for turn in turns],
    )


@router.post("/{session_id}/turn", response_model=ResearchTurnRead)
async def add_turn(
    session_id: str,
    payload: ResearchTurnRequest,
    service: Annotated[ResearchChatService, Depends(get_research_chat_service)],
) -> ResearchTurnRead:
    """Add a user turn and answer it: research or vault-grounded.

    A message with a curated web trigger ("buscar en la web X", "buscá en
    internet X", ...) runs the §21 flow and the answer links the persisted
    report; any other message is answered grounded in the vault with the
    session's history as context. Empty messages are rejected by the schema
    (422); an unreachable search provider answers 503; infrastructure
    failures inside research answer 502.
    """
    try:
        turn = await service.add_turn(session_id, payload.message)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Research session not found")
    except SearchUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_SEARCH_UNAVAILABLE
        )
    except ResearchError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Research failed: {exc}",
        ) from exc
    except LLMProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Research session answer failed: {exc}",
        ) from exc
    return _turn_read(turn)


@router.post(
    "/{session_id}/tutorial",
    response_model=TutorialRead,
    status_code=status.HTTP_201_CREATED,
)
async def save_tutorial(
    session_id: str,
    payload: ResearchTutorialRequest,
    service: Annotated[ResearchChatService, Depends(get_research_chat_service)],
) -> TutorialRead:
    """Save the session's topic as a depth-aware tutorial in the vault.

    Retrieval already sees the session's research reports (they are ingested
    when the §21 flow persists them), so the tutorial is grounded on the
    session's research. Unknown modes are rejected by the schema (422).
    """
    try:
        result = await service.save_tutorial(session_id, payload.mode)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Research session not found")
    return TutorialRead(
        document_id=result.document_id,
        title=result.title,
        file_path=result.file_path,
        content=result.content,
        sources=[
            TutorialSourceRead(title=source.title, score=source.score)
            for source in result.sources
        ],
        warnings=result.warnings,
        mode=result.mode,
    )