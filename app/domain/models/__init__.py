"""Domain models. Importing this package registers every table on
`Base.metadata` (required before Alembic autogenerate and create_all).
"""

from app.domain.models.base import Base
from app.domain.models.document import Chunk, Document
from app.domain.models.eval import EvalCase, EvalRun
from app.domain.models.memory import Memory
from app.domain.models.project import Project
from app.domain.models.usage import LLMUsage

__all__ = ["Base", "Chunk", "Document", "EvalCase", "EvalRun", "LLMUsage", "Memory", "Project"]