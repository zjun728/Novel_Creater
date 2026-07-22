"""Generation-aware creation-contract service package."""

from .confirmation import ContractService
from .drafts import (
    AssetRevisionRef,
    BindingContractRef,
    ConfirmContracts,
    ConfirmedContractResult,
    ContractConflict,
    ContractDraftIncomplete,
    ContractDraftInput,
    ContractDraftPayload,
    ContractDraftResult,
    ContractNotFound,
    ContractPreconditionFailed,
    CorpusSourceRef,
    EngineContractRef,
    ModelBindingRef,
    ResolvedAssetRef,
    ResolvedCorpusFragment,
    ResolvedCorpusRef,
    ResolvedStyleRef,
    SaveContractDraft,
    SeedContractRef,
    _strict_engine,
    style_contract_hash,
)

__all__ = (
    "AssetRevisionRef", "BindingContractRef", "ConfirmContracts",
    "ConfirmedContractResult", "ContractConflict", "ContractDraftIncomplete",
    "ContractDraftInput", "ContractDraftPayload", "ContractDraftResult",
    "ContractNotFound", "ContractPreconditionFailed", "ContractService",
    "CorpusSourceRef", "EngineContractRef", "ModelBindingRef",
    "ResolvedAssetRef", "ResolvedCorpusFragment", "ResolvedCorpusRef",
    "ResolvedStyleRef", "SaveContractDraft", "SeedContractRef",
    "_strict_engine", "style_contract_hash",
)
