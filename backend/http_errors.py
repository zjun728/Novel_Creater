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


class ProjectArchived(PublicDomainError):
    status_code = 409
    code = "ProjectArchived"
    message = "Project is archived"


class ProjectLifecycleConflict(PublicDomainError):
    status_code = 409
    code = "ProjectLifecycleConflict"
    message = "Project lifecycle changed; refresh and retry"


class ProjectBusy(PublicDomainError):
    status_code = 409
    code = "ProjectBusy"
    message = "Project has an unfinished operation"


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


class AssetNotFound(PublicDomainError):
    status_code = 404
    code = "AssetNotFound"
    message = "Asset or project not found"


class AssetRecommendationConflict(PublicDomainError):
    status_code = 409
    code = "AssetRecommendationConflict"
    message = "Asset recommendation inputs changed; refresh and retry"


class AssetCatalogNotReady(PublicDomainError):
    status_code = 503
    code = "AssetCatalogNotReady"
    message = "Approved writing assets are not ready"


class CorpusImportConflict(PublicDomainError):
    status_code = 409
    code = "CorpusImportConflict"
    message = "Corpus import key was already used for a different request"


class CorpusResourceNotFound(PublicDomainError):
    status_code = 404
    code = "CorpusResourceNotFound"
    message = "Corpus resource not found"


class CorpusImportFailed(PublicDomainError):
    status_code = 422
    code = "CorpusImportFailed"
    message = "Corpus import could not be completed"


class CorpusRequestInvalid(PublicDomainError):
    status_code = 422
    code = "CorpusRequestInvalid"
    message = "Corpus request is invalid"
