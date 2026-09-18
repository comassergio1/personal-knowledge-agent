"""Unit tests for research-intent detection (v1 heuristic, spec §19).

Pins the curated trigger truth table, case-insensitivity, whitespace
collapsing, and the message length cap boundary on the pure function.
"""

from __future__ import annotations

import pytest

from app.api.routes.research_intent import (
    RESEARCH_MAX_LENGTH,
    RESEARCH_TRIGGERS,
    is_research_request,
)

_TRIGGER = "investigá en la web"


def _message_of_length(length: int) -> str:
    """A message of exactly ``length`` characters that contains _TRIGGER."""
    assert length >= len(_TRIGGER)
    return "x" * (length - len(_TRIGGER)) + _TRIGGER


# -- truth table -------------------------------------------------------------


@pytest.mark.parametrize("trigger", RESEARCH_TRIGGERS)
def test_each_trigger_matches(trigger: str) -> None:
    assert is_research_request(f"por favor {trigger} qué es asyncio")


@pytest.mark.parametrize(
    "question",
    [
        "¿Qué es asyncio?",
        "What can you tell me about anchovies?",
        "Resumí la nota sobre anchoas",
        "hola",
        "decime qué dice mi documento",
        "¿cuántos grados son 25 celsius?",
        "Necesito el clima para mañana",
    ],
)
def test_unrelated_questions_do_not_trigger(question: str) -> None:
    assert not is_research_request(question)


def test_empty_message_does_not_trigger() -> None:
    assert not is_research_request("")
    assert not is_research_request("   ")


# -- case-insensitivity ------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "INVESTIGÁ EN LA WEB qué es asyncio",
        "Research async in Python",
        "SEARCH THE WEB for asyncio",
        "Buscá Fuentes sobre pydantic",
        "Look Up On The Web, por favor",
    ],
)
def test_matching_is_case_insensitive(message: str) -> None:
    assert is_research_request(message)


# -- whitespace robustness ---------------------------------------------------


def test_whitespace_is_collapsed_before_matching() -> None:
    assert is_research_request("investigá   qué   es   asyncio")
    assert is_research_request("  buscá en la web: asyncio  ")
    assert is_research_request("investigá\tqué\tes\nasyncio")


# -- length cap --------------------------------------------------------------


def test_message_at_the_cap_can_trigger() -> None:
    message = _message_of_length(RESEARCH_MAX_LENGTH)
    assert len(message) == RESEARCH_MAX_LENGTH
    assert is_research_request(message)


def test_message_one_char_below_the_cap_triggers() -> None:
    message = _message_of_length(RESEARCH_MAX_LENGTH - 1)
    assert len(message) == RESEARCH_MAX_LENGTH - 1
    assert is_research_request(message)


def test_message_one_char_over_the_cap_does_not_trigger() -> None:
    message = _message_of_length(RESEARCH_MAX_LENGTH + 1)
    assert len(message) == RESEARCH_MAX_LENGTH + 1
    assert not is_research_request(message)


def test_cap_applies_to_the_raw_message_before_whitespace_collapsing() -> None:
    message = f"{_TRIGGER} " + "x " * 200
    assert len(message) > RESEARCH_MAX_LENGTH
    assert not is_research_request(message)


# -- documented coarse behavior ----------------------------------------------


def test_coarse_spanish_triggers_fire_by_design() -> None:
    # "en internet"/"en la web" are substring triggers (documented false
    # positives on purpose). Pinning the behavior keeps a future trigger-list
    # change a conscious decision.
    assert is_research_request("¿qué dice mi nota en internet?")
    assert is_research_request("¿hay algo en la web sobre asyncio?")