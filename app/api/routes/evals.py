"""Evaluation endpoints: run datasets and read run history (spec §31/§32)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import get_eval_service
from app.schemas.eval import EvalRequest, EvalRunHistoryRead, EvalRunRead
from app.services.eval_service import EvalService

router = APIRouter(prefix="/evals", tags=["evals"])


@router.post("/run", response_model=EvalRunRead, status_code=status.HTTP_201_CREATED)
async def run_evals(
    request: EvalRequest,
    eval_service: Annotated[EvalService, Depends(get_eval_service)],
) -> EvalRunRead:
    """Run one evaluation dataset; each case resolves independently.

    Empty/invalid datasets are rejected by the schema (422). Nothing aborts
    the batch: a failing case is persisted with verdict ``error`` and the
    remaining cases still run.
    """
    return await eval_service.run(
        request.dataset,
        project_id=request.project_id,
        top_k=request.top_k,
        thresholds=request.thresholds,
    )


@router.get("/runs", response_model=EvalRunHistoryRead)
async def list_eval_runs(
    eval_service: Annotated[EvalService, Depends(get_eval_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> EvalRunHistoryRead:
    """Return the most recent evaluation runs, newest first."""
    return await eval_service.history(limit=limit)