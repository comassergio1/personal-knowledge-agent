"""Tutorial endpoint: generate grounded Spanish tutorials (spec §20)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_tutorial_service
from app.providers.llm.base import LLMProviderError
from app.schemas.tutorial import TutorialRead, TutorialRequest, TutorialSourceRead
from app.services.tutorial_service import TutorialService

router = APIRouter(prefix="/tutorials", tags=["tutorials"])


@router.post(
    "/generate", response_model=TutorialRead, status_code=status.HTTP_201_CREATED
)
async def generate_tutorial(
    request: TutorialRequest,
    tutorial_service: Annotated[TutorialService, Depends(get_tutorial_service)],
) -> TutorialRead:
    """Generate a tutorial for ``objective``, persist it, and return it.

    Empty objectives are rejected by the schema (422); LLM provider failures
    surface as 502. ``mode`` selects the tutorial depth and is echoed back on
    the response. The tutorial is written into the vault and indexed
    immediately, so re-reading, deleting, and re-syncing reuse the existing
    documents endpoints.
    """
    try:
        result = await tutorial_service.generate(
            request.objective,
            project_id=request.project_id,
            title=request.title,
            mode=request.mode,
        )
        await tutorial_service.persist(
            result, project_id=request.project_id, title=request.title
        )
    except LLMProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Tutorial generation failed: {exc}",
        ) from exc
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