"""Stable public domain errors for HTTP-safe application boundaries."""

from __future__ import annotations


class PublicDomainError(RuntimeError):
    status_code = 400
    code = "DomainError"
    message = "The request could not be completed"

    def __init__(self) -> None:
        super().__init__(self.message)


class ProjectNotFound(PublicDomainError):
    status_code = 404
    code = "ProjectNotFound"
    message = "Project not found"


class SeedNotFound(PublicDomainError):
    status_code = 404
    code = "SeedNotFound"
    message = "Seed or project not found"


class SeedConflict(PublicDomainError):
    status_code = 409
    code = "SeedConflict"
    message = "Seed state changed; refresh and retry"


class SeedLocked(PublicDomainError):
    status_code = 423
    code = "SeedLocked"
    message = "Seed changes are locked after final chapter creation"


class BindingNotFound(PublicDomainError):
    status_code = 404
    code = "BindingNotFound"
    message = "Project binding not found"


class BindingConflict(PublicDomainError):
    status_code = 409
    code = "BindingConflict"
    message = "Binding state changed; refresh and retry"


class BindingProviderUnavailable(PublicDomainError):
    status_code = 422
    code = "BindingProviderUnavailable"
    message = "A selected provider is unavailable"


class StoryEngineBatchNotFound(PublicDomainError):
    status_code = 404
    code = "StoryEngineBatchNotFound"
    message = "Story engine batch or project not found"


class StoryEngineBatchConflict(PublicDomainError):
    status_code = 409
    code = "StoryEngineBatchConflict"
    message = "Story engine batch state changed; refresh and retry"


class StoryEnginePreconditionFailed(PublicDomainError):
    status_code = 422
    code = "StoryEnginePreconditionFailed"
    message = "Story engine prerequisites are unavailable"
