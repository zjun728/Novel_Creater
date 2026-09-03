"""Generation-aware creation-contract service package."""

from .confirmation import ContractService
from .drafts import (
    AssetRevisionRef,
    BindingContractRef,
    ConfirmContracts,
    ConfirmedContractResult,
    ContractAlreadyConfirmed,
    ContractConflict,
    ContractDraftIncomplete,
    ContractDraftDocumentProjection,
    ContractDraftInput,
    ContractDraftPayload,
    ContractDraftResult,
    ContractStyleDisplay,
    ContractHistoryPage,
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
    "ConfirmedContractResult", "ContractAlreadyConfirmed", "ContractConflict", "ContractDraftIncomplete",
    "ContractDraftDocumentProjection", "ContractDraftInput", "ContractDraftPayload", "ContractDraftResult",
    "ContractHistoryPage", "ContractNotFound", "ContractPreconditionFailed",
    "ContractService",
    "CorpusSourceRef", "EngineContractRef", "ModelBindingRef",
    "ResolvedAssetRef", "ResolvedCorpusFragment", "ResolvedCorpusRef",
    "ResolvedStyleRef", "ContractStyleDisplay", "SaveContractDraft", "SeedContractRef",
    "_strict_engine", "style_contract_hash",
)
