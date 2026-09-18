"""Unit tests for secret redaction (spec §34): present → marker, absent → unchanged."""

from __future__ import annotations

from app.services.redaction import REDACTED_MARKER, redact_secrets


def test_key_value_assignments_are_redacted() -> None:
    text = "password=hunter2, api_key=abc123, token=xyz, secret=s3cr3t"
    result = redact_secrets(text)
    assert REDACTED_MARKER in result
    for secret in ("hunter2", "abc123", "xyz", "s3cr3t"):
        assert secret not in result


def test_key_value_case_and_whitespace_variants() -> None:
    assert "letmein" not in redact_secrets("PASSWORD = letmein")
    assert "letmein" not in redact_secrets("Passwd=letmein")
    assert "k-9" not in redact_secrets("APIKey =k-9")
    assert "k-9" not in redact_secrets("api_key = k-9")
    assert "t0k" not in redact_secrets("\tToken=t0k\n")
    assert "vv" not in redact_secrets("secret='vv'")


def test_key_value_value_runs_to_eol_or_comma() -> None:
    result = redact_secrets("password=abc\nnext line stays")
    assert "next line stays" in result
    # The value stops at a comma, so a second assignment on the same line is
    # still redacted.
    result = redact_secrets("token=t1, secret=t2")
    assert "t1" not in result
    assert "t2" not in result


def test_key_name_without_assignment_is_untouched() -> None:
    text = "Remember the password before deleting the token file."
    assert redact_secrets(text) == text


def test_bearer_tokens_are_redacted() -> None:
    text = "Use Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def to call the API"
    result = redact_secrets(text)
    assert "eyJhbGci" not in result
    assert REDACTED_MARKER in result


def test_bearer_multiword_to_eol() -> None:
    text = "Bearer alpha bravo charlie\nnext line stays"
    result = redact_secrets(text)
    assert "alpha" not in result
    assert "charlie" not in result
    assert "next line stays" in result


def test_bearer_case_insensitive() -> None:
    assert "q-w" not in redact_secrets("bearer q-w")


def test_authorization_header_value_is_redacted() -> None:
    text = "Authorization: Basic dXNlcjpwYXNz\nAuthorization: Bearer abc.def"
    result = redact_secrets(text)
    assert "dXNlcjpwYXNz" not in result
    assert "abc.def" not in result


def test_private_key_blocks_are_redacted() -> None:
    pem = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA7g==\n"
        "-----END RSA PRIVATE KEY-----\n"
        "public summary follows"
    )
    result = redact_secrets(pem)
    assert "MIIEowIBAAKCAQEA7g==" not in result
    assert REDACTED_MARKER in result
    assert "public summary follows" in result


def test_ssh_public_key_blobs_are_redacted() -> None:
    ssh_key = (
        "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQDlZk9Za4vJfGx2NpQwR7TbYsUeWaVcXdFgHiJkLm"
        "NoPrQsTuVwXyZ1A2B3C4D5E6F7 user@host"
    )
    result = redact_secrets(f"key: {ssh_key}")
    assert "AAAAB3NzaC1yc2EAAAADAQABAAABgQDlZk9Za4vJfGx2NpQwR7TbYsUeWaVcXdFgHiJkLm" not in result
    assert REDACTED_MARKER in result


def test_aws_access_key_ids_are_redacted() -> None:
    text = "access key AKIAIOSFODNN7EXAMPLE is active"
    result = redact_secrets(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in result
    assert "access key" in result


def test_jwt_tokens_are_redacted() -> None:
    jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "dGhlLXNpZ25hdHVyZS12YWx1ZQ"
    )
    result = redact_secrets(f"token: {jwt}")
    assert "eyJhbGci" not in result
    assert "dGhlLXNpZ25hdHVyZS12YWx1ZQ" not in result


def test_plain_text_passes_through_unchanged() -> None:
    text = "The user prefers concise answers and Obsidian-style notes."
    assert redact_secrets(text) == text


def test_empty_input_returns_empty() -> None:
    assert redact_secrets("") == ""


def test_marker_is_constant() -> None:
    assert REDACTED_MARKER == "[REDACTED]"