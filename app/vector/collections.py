"""Vector store collection constants shared by the Qdrant layer (spec §9)."""

from __future__ import annotations

DEFAULT_COLLECTION = "knowledge"
MEMORIES_COLLECTION = "memories"

# Payload field names stored on every chunk point.
DOCUMENT_ID_FIELD = "document_id"
PROJECT_ID_FIELD = "project_id"
CHUNK_ID_FIELD = "chunk_id"
CHUNK_INDEX_FIELD = "chunk_index"
TITLE_FIELD = "title"
CONTENT_FIELD = "content"
FILE_PATH_FIELD = "file_path"
METADATA_FIELD = "metadata"

# Payload field names stored on every memory point (its own collection).
MEMORY_ID_FIELD = "memory_id"
MEMORY_TYPE_FIELD = "memory_type"