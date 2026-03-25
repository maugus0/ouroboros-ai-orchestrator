"""Shared Pydantic models used across the application."""

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class StandardResponse(BaseModel, Generic[T]):
    """Uniform API response envelope."""

    success: bool = True
    message: str = "OK"
    data: T | None = None


class ErrorResponse(BaseModel):
    """Uniform error response."""

    success: bool = False
    message: str
    detail: str | None = None


class PaginationParams(BaseModel):
    """Query parameters for paginated list endpoints."""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated list wrapper."""

    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int
