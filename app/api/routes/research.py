"""Research endpoint: run a web research report and persist it (spec §21)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_research_service, get_search_provider
from app.providers.search.base import SearchProvider
from app.schemas.research import ResearchRead, ResearchRequest, ResearchSourceRead
from app.services.research_service import ResearchError, ResearchService

router = APIRouter(prefix="/research", tags=["research"])

# User-facing copy for the SearXNG outage case (Spanish, spec §21).
_SEARCH_UNAVAILABLE = (
    "El buscador SearXNG no responde. Verifique que el servicio esté "
    "disponible e intente nuevamente."
)


@router.post("/run", response_model=ResearchRead, status_code=status.HTTP_201_CREATED)
async def run_research(
    request: ResearchRequest,
    research_service: Annotated[ResearchService, Depends(get_research_service)],
    search_provider: Annotated[SearchProvider, Depends(get_search_provider)],
) -> ResearchRead:
    """Run the §21 flow and return the persisted Spanish report.

    The SearXNG instance is probed before the run: an unreachable instance
    answers 503 with a clear message and the rest of the API stays healthy.
    Empty questions are rejected by the schema (422); infra failures inside
    the flow (LLM, search, ingestion) are message-chained ``ResearchError``
    and surface as 502.
    """
    if not await search_provider.ping():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_SEARCH_UNAVAILABLE
        )
    try:
        result = await research_service.run(
            request.question,
            project_id=request.project_id,
            title=request.title,
            max_sources=request.max_sources,
        )
    except ResearchError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Research failed: {exc}",
        ) from exc
    return ResearchRead(
        document_id=result.document_id,
        title=result.title,
        file_path=result.file_path,
        report=result.report,
        sources=[
            ResearchSourceRead(
                title=source.title,
                url=source.url,
                domain=source.domain,
                snippet=source.snippet,
            )
            for source in result.sources
        ],
        warnings=result.warnings,
    )