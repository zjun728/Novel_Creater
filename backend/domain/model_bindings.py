"""Immutable model-provider binding revisions."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


TASK_KEYS = (
    "seed",
    "planning",
    "writing",
    "audit",
    "summary",
    "extraction",
    "polish",
    "market",
)

TaskKey = Literal[
    "seed",
    "planning",
    "writing",
    "audit",
    "summary",
    "extraction",
    "polish",
    "market",
]
ResolutionStatus = Literal["bound", "unbound"]


class BindingItem(BaseModel):
    """One task's resolved or explicitly unbound provider snapshot."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    task_key: TaskKey
    resolution_status: ResolutionStatus
    provider_id: str | None = Field(default=None, min_length=1)
    provider_name_snapshot: str | None = Field(default=None, min_length=1)
    model_name_snapshot: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_resolution(self) -> Self:
        provider_values = (
            self.provider_id,
            self.provider_name_snapshot,
            self.model_name_snapshot,
        )
        if self.resolution_status == "bound" and any(
            value is None for value in provider_values
        ):
            raise ValueError("bound items require all provider snapshot fields")
        if self.resolution_status == "unbound" and any(
            value is not None for value in provider_values
        ):
            raise ValueError("unbound items require empty provider snapshot fields")
        return self


class BindingRevision(BaseModel):
    """A complete immutable snapshot of all model binding tasks."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    project_id: str = Field(min_length=1)
    revision: int = Field(gt=0)
    items: tuple[BindingItem, ...]

    @model_validator(mode="after")
    def validate_task_keys(self) -> Self:
        item_keys = tuple(item.task_key for item in self.items)
        if len(item_keys) != len(TASK_KEYS) or set(item_keys) != set(TASK_KEYS):
            raise ValueError("items must contain each task key exactly once")
        if item_keys != TASK_KEYS:
            raise ValueError("items must follow TASK_KEYS canonical order")
        return self

    @property
    def binding_complete(self) -> bool:
        """Whether every task key has exactly one binding item."""

        item_keys = tuple(item.task_key for item in self.items)
        return len(item_keys) == len(TASK_KEYS) and set(item_keys) == set(TASK_KEYS)

    @property
    def binding_ready(self) -> bool:
        """Whether the complete revision has every task bound."""

        return self.binding_complete and all(
            item.resolution_status == "bound" for item in self.items
        )
