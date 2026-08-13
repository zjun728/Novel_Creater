"""Temporary style-trial route backed only by the server-side seed binding."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.database import transaction
from backend.domain.style_trials import (
    GenerateStyleTrial,
    STYLE_TRIAL_HASH_PATTERN,
    STYLE_TRIAL_IDEMPOTENCY_PATTERN,
    STYLE_TRIAL_IDENTIFIER_PATTERN,
    STYLE_TRIAL_MAX_IDENTIFIER_LENGTH,
    STYLE_TRIAL_MAX_SCENARIO_LENGTH,
)
from backend.gateways.style_trial_provider import StyleTrialProviderGateway
from backend.repositories.style_trials import StyleTrialRepository
from backend.services.style_trials import StyleTrialService


router = APIRouter(tags=["style-trials"])
_service = StyleTrialService(
    StyleTrialRepository(),
    transaction_factory=transaction,
    provider_gateway=StyleTrialProviderGateway(),
)


def get_style_trial_service() -> StyleTrialService:
    return _service


class StyleTrialBody(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )

    selectionRevision: int = Field(gt=0)
    engineOptionId: str = Field(
        min_length=1,
        max_length=STYLE_TRIAL_MAX_IDENTIFIER_LENGTH,
        pattern=STYLE_TRIAL_IDENTIFIER_PATTERN,
    )
    engineHash: str = Field(pattern=STYLE_TRIAL_HASH_PATTERN)
    primaryStyleRevisionId: str = Field(
        min_length=1,
        max_length=STYLE_TRIAL_MAX_IDENTIFIER_LENGTH,
        pattern=STYLE_TRIAL_IDENTIFIER_PATTERN,
    )
    primaryStyleHash: str = Field(pattern=STYLE_TRIAL_HASH_PATTERN)
    secondaryStyleRevisionId: str | None = Field(
        default=None,
        min_length=1,
        max_length=STYLE_TRIAL_MAX_IDENTIFIER_LENGTH,
        pattern=STYLE_TRIAL_IDENTIFIER_PATTERN,
    )
    secondaryStyleHash: str | None = Field(
        default=None, pattern=STYLE_TRIAL_HASH_PATTERN
    )
    authorScenario: str = Field(
        min_length=1, max_length=STYLE_TRIAL_MAX_SCENARIO_LENGTH
    )
    idempotencyKey: str = Field(
        min_length=64,
        max_length=64,
        pattern=STYLE_TRIAL_IDEMPOTENCY_PATTERN,
    )

    @model_validator(mode="after")
    def validate_secondary_style(self):
        if (self.secondaryStyleRevisionId is None) != (
            self.secondaryStyleHash is None
        ):
            raise ValueError("secondary style identity must be complete")
        if self.secondaryStyleRevisionId == self.primaryStyleRevisionId:
            raise ValueError("primary and secondary styles must be different")
        return self


@router.post("/projects/{pid}/style-trials")
async def generate_style_trial(
    pid: Annotated[
        str,
        Path(
            min_length=1,
            max_length=STYLE_TRIAL_MAX_IDENTIFIER_LENGTH,
            pattern=STYLE_TRIAL_IDENTIFIER_PATTERN,
        ),
    ],
    body: StyleTrialBody,
    service: StyleTrialService = Depends(get_style_trial_service),
):
    result = await service.generate(
        GenerateStyleTrial(
            project_id=pid,
            selection_revision=body.selectionRevision,
            engine_option_id=body.engineOptionId,
            engine_hash=body.engineHash,
            primary_style_revision_id=body.primaryStyleRevisionId,
            primary_style_hash=body.primaryStyleHash,
            secondary_style_revision_id=body.secondaryStyleRevisionId,
            secondary_style_hash=body.secondaryStyleHash,
            author_scenario=body.authorScenario,
            idempotency_key=body.idempotencyKey,
        )
    )
    return {
        "attemptId": result.attempt_id,
        "status": result.status,
        "sample": result.sample,
        "resultHash": result.result_hash,
        "publicErrorCode": result.public_error_code,
        "provider": {
            "providerId": result.provider.provider_id,
            "providerType": result.provider.provider_type,
            "modelName": result.provider.model_name,
            "profileRevision": result.provider.profile_revision,
        },
        "createdAt": result.created_at,
        "completedAt": result.completed_at,
    }


__all__ = ("get_style_trial_service", "router")
