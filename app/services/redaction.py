"""Secret redaction for knowledge candidates (spec §34).

``redact_secrets()`` replaces credential-shaped text (passwords, api keys,
bearer tokens, authorization headers, private key blocks, ssh public keys,
AWS keys, JWTs) with a constant marker before a candidate is stored, so
secrets never reach the knowledge database or the vector store.

Redaction is a defense-in-depth layer that protects *stored knowledge*; it is
not key management. Primary credential handling stays where it belongs — the
runtime environment only (spec §27).
"""

from __future__ import annotations

import re

REDACTED_MARKER = "[REDACTED]"

# PEM private-key blocks span multiple lines (DOTALL); handled first so the
# content inside is never seen by the narrower patterns below.
_PEM_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)

# key=value assignments (password=, api_key=, apikey=, token=, secret=);
# the value runs to end-of-line or a comma. Case-insensitive.
_KEY_VALUE_RE = re.compile(
    r"(?i)\b(?:password|passwd|api_?key|token|secret)\s*=\s*[^,\n]*"
)

# `Bearer <token>` headers; single or multiword token. Spaces/tabs only —
# ``\s`` would cross a line break and swallow the rest of the paragraph.
_BEARER_RE = re.compile(
    r"(?i)\bbearer[ \t]+[A-Za-z0-9._~+/=-]+(?:[ \t]+[A-Za-z0-9._~+/=-]+)*"
)

# Authorization header values (any scheme: bearer, basic, custom...).
_AUTH_HEADER_RE = re.compile(r"(?i)\bauthorization\s*:\s*[^\r\n]+")

# ssh public key blobs: `ssh-rsa AAAA... comment`.
_SSH_KEY_RE = re.compile(
    r"\bssh-(?:rsa|dss|ecdsa|ed25519)[ \t]+[A-Za-z0-9+/]{40,}={0,2}(?:[ \t]+\S+)?"
)

# AWS access key id (AKIA + 16 base62 chars).
_AWS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")

# JWT-ish tokens, lenient: eyJ... prefix + two (or three) base64url segments.
_JWT_RE = re.compile(r"\beyJ[a-zA-Z0-9_-]{8,}\.[a-zA-Z0-9_-]{8,}(?:\.[a-zA-Z0-9_-]+)?")


def redact_secrets(text: str) -> str:
    """Return ``text`` with every recognized secret replaced by the marker.

    The function is pure: given the same input it always returns the same
    output and never touches external state. Patterns are applied in order
    (PEM blocks first); text without secrets passes through unchanged.
    """
    redacted = _PEM_BLOCK_RE.sub(REDACTED_MARKER, text)
    for pattern in (_KEY_VALUE_RE, _BEARER_RE, _AUTH_HEADER_RE, _SSH_KEY_RE, _AWS_KEY_RE, _JWT_RE):
        redacted = pattern.sub(REDACTED_MARKER, redacted)
    return redacted