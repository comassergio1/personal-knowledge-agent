"""Unit tests for app.core.config.Settings."""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings, get_settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_TEMPLATE = PROJECT_ROOT / "env.template"

# Exactly the names documented in spec §27 / env.template.
EXPECTED_ENV_NAMES = 28


def test_settings_defaults_match_env_example() -> None:
    settings = Settings(_env_file=None)
    checked = 0
    for line in ENV_TEMPLATE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        field_name = name.strip().lower()
        assert field_name in Settings.model_fields, f"Settings is missing field for {name}"
        assert (
            str(getattr(settings, field_name)) == value.strip()
        ), f"default mismatch for {name}"
        checked += 1
    assert checked == EXPECTED_ENV_NAMES


def test_environment_overrides_defaults(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./data/override.db")
    monkeypatch.setenv("LLM_MODEL", "llama3.1:latest")

    settings = Settings(_env_file=None)

    assert settings.app_env == "production"
    assert settings.database_url == "sqlite+aiosqlite:///./data/override.db"
    assert settings.llm_model == "llama3.1:latest"
    # Unset variables keep their defaults.
    assert settings.embedding_provider == "ollama"
    assert settings.llm_provider == "ollama"


def test_unknown_environment_variables_are_ignored(monkeypatch) -> None:
    monkeypatch.setenv("UNRELATED_VAR", "x")
    settings = Settings(_env_file=None)
    assert not hasattr(settings, "unrelated_var")


def test_get_settings_is_a_cached_singleton() -> None:
    assert get_settings() is get_settings()