"""Vector store collection constants shared by the Qdrant layer (spec §9)."""

from __future__ import annotations

DEFAULT_COLLECTION = "knowledge"

# Payload field names stored on every chunk point.
DOCUMENT_ID_FIELD = "document_id"
CHUNK_ID_FIELD = "chunk_id"
CHUNK_INDEX_FIELD = "chunk_index"
TITLE_FIELD = "title"
CONTENT_FIELD = "content"
METADATA_FIELD = "metadata"