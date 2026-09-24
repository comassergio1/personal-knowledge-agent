"""Unit tests for research-session trigger detection and target extraction.

Pins the curated conservative trigger truth table (explicit verb + location
only, NOT the broad ``research_intent`` patterns), whitespace normalization,
case-insensitivity, and the target-extraction rule on the pure functions.
"""

from __future__ import annotations

import pytest

from app.services.research_chat_service import (
    RESEARCH_TRIGGERS,
    detect_trigger,
    extract_target,
)

# -- truth table -------------------------------------------------------------


@pytest.mark.parametrize("trigger", RESEARCH_TRIGGERS)
def test_each_trigger_matches(trigger: str) -> None:
    assert detect_trigger(f"por favor {trigger} que es asyncio") == trigger


@pytest.mark.parametrize(
    "message",
    [
        "Que es asyncio?",
        "explicame que dice mi nota",
        "hola",
        "",
        "   ",
        # Broad research_intent patterns are deliberately NOT triggers here:
        # bare "en la web" / "en internet" must never fire, and neither does
        # "buscá fuentes" (verb without an explicit location).
        "hay algo en la web sobre asyncio?",
        "que dice mi nota en internet?",
        "buscá fuentes sobre pydantic",
        "busca fuentes",
        "investigación sobre asyncio",
        "research async in python",
    ],
)
def test_conservative_triggers_do_not_fire(message: str) -> None:
    assert detect_trigger(message) is None


# -- case-insensitivity ------------------------------------------------------


@pytest.mark.parametrize(
    "message, expected",
    [
        ("BUSCAR EN LA WEB asyncio", "buscar en la web"),
        ("Busca En Internet pydantic", "busca en internet"),
        ("Buscá en internet VLANs", "buscá en internet"),
        ("INVESTIGÁ EN LA WEB docker", "investigá en la web"),
        ("Investiga en la web qdrant", "investiga en la web"),
        ("Buscar en internet ollama", "buscar en internet"),
        ("Buscá en la web redes", "buscá en la web"),
        ("Investigar en la web kubernetes", "investigar en la web"),
    ],
)
def test_matching_is_case_insensitive(message: str, expected: str) -> None:
    assert detect_trigger(message) == expected


# -- whitespace normalization -------------------------------------------------


def test_whitespace_is_collapsed_before_matching() -> None:
    assert detect_trigger("buscá   en   la   web asyncio") == "buscá en la web"
    assert detect_trigger("  buscar en la web: asyncio  ") == "buscar en la web"
    assert detect_trigger("busca\tEn\ninternet\npydantic") == "busca en internet"


# -- target extraction --------------------------------------------------------


def test_target_is_message_minus_trigger() -> None:
    message = "buscar en la web que es asyncio"
    assert extract_target(message, "buscar en la web") == "que es asyncio"


@pytest.mark.parametrize(
    "message, expected",
    [
        ("buscá en la web: asyncio", "asyncio"),
        ("busca en internet, pydantic", "pydantic"),
        ("investigá en la web — docker compose", "docker compose"),
        ("BUSCAR EN LA WEB ¿qué es asyncio?", "qué es asyncio"),
        ("Investiga en la web VLANs!", "vlans"),
        ("buscar en internet .fastapi", "fastapi"),
    ],
)
def test_target_strips_separators_around_the_trigger(message: str, expected: str) -> None:
    trigger = detect_trigger(message)
    assert trigger is not None
    assert extract_target(message, trigger) == expected


def test_bare_trigger_extracts_an_empty_target() -> None:
    message = "Buscá en la web"
    trigger = detect_trigger(message)
    assert trigger == "buscá en la web"
    assert extract_target(message, trigger) == ""


def test_target_keeps_text_before_the_trigger() -> None:
    # The trigger can sit mid-sentence; the leading connector survives as-is.
    # Documented coarse behavior: a trigger in the middle of a longer request
    # still fires, and everything outside the trigger phrase becomes the
    # target (the research flow is robust to a loose question).
    assert extract_target(
        "contame, buscá en la web que es asyncio", "buscá en la web"
    ) == "contame, que es asyncio"


def test_detect_trigger_prefers_earliest_and_longest_match() -> None:
    # "investigar en la web" starts before "busca en internet"; the earliest
    # occurrence wins. Ties cannot happen (no trigger is a prefix of another
    # at the same position), but the rule is pinned anyway.
    message = "investigar en la web primero y busca en internet después"
    assert detect_trigger(message) == "investigar en la web"


def test_extract_target_returns_empty_for_unknown_trigger() -> None:
    # Defensive: an extracted trigger is always one we returned, so the
    # absence path can never be reached in production.
    assert extract_target("cualquier frase", "no existe") == ""