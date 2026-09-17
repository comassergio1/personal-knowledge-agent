"""Declarative base for all domain models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Common base class for PKA mapped models."""