"""Unit tests for the research source-quality heuristic (spec §21 tiers)."""

from __future__ import annotations

from app.services.research_service import source_quality

# Official documentation hosts → tier 3.


def test_official_docs_tier() -> None:
    assert source_quality("https://docs.python.org/3/library/asyncio.html") == 3
    assert source_quality("https://learn.microsoft.com/es-es/azure/") == 3
    assert source_quality("https://developers.google.com/tech-writing") == 3
    assert source_quality("https://github.com/python/cpython") == 3
    assert source_quality("https://gist.github.com/user/123") == 3
    assert source_quality("https://pandas.readthedocs.io/en/stable/") == 3
    assert source_quality("https://www.w3.org/TR/html52/") == 3
    assert source_quality("https://developer.mozilla.org/es/docs/Web/") == 3
    assert source_quality("https://www.kernel.org/doc/html/latest/") == 3
    assert source_quality("https://es.wikipedia.org/wiki/Asyncio") == 3
    assert source_quality("https://wikipedia.org/wiki/Asyncio") == 3


# Mainstream technology media → tier 2.


def test_mainstream_tech_tier() -> None:
    assert source_quality("https://stackoverflow.com/questions/1/asyncio") == 2
    assert source_quality("https://www.stackoverflow.com/questions/1/x") == 2
    assert source_quality("https://dev.to/author/asyncio-guide") == 2
    assert source_quality("https://blog.dev.to/team/a-post") == 2
    assert source_quality("https://medium.com/@writer/asyncio") == 2
    assert source_quality("https://towardsdatascience.com/asyncio-in-python") == 2
    assert source_quality("https://guide.blogspot.com/2026/asyncio") == 2
    assert source_quality("https://www.wired.com/story/asyncio/") == 2
    assert source_quality("https://arstechnica.com/information-technology/") == 2
    assert source_quality("https://www.theverge.com/2026/1/1/x") == 2
    assert source_quality("https://www.howtogeek.com/888/asyncio/") == 2
    assert source_quality("https://realpython.com/async-io-python/") == 2


# Community / forums → tier 1.


def test_community_tier() -> None:
    assert source_quality("https://www.reddit.com/r/Python/comments/x/") == 1
    assert source_quality("https://reddit.com/r/Python/") == 1
    assert source_quality("https://forums.linuxmint.com/viewtopic.php?t=1") == 1
    assert source_quality("https://es.quora.com/Por-que-usar-asyncio") == 1
    assert source_quality("https://superuser.stackexchange.com/q/123") == 1


# Anything else, malformed, or non-http(s) → tier 0.


def test_unknown_and_unusable_urls_tier_zero() -> None:
    assert source_quality("https://example.org/page") == 0
    assert source_quality("https://random-blog.example.net/post") == 0
    assert source_quality("javascript:alert(1)") == 0
    assert source_quality("ftp://example.com/file.txt") == 0
    assert source_quality("not a url") == 0
    assert source_quality("") == 0