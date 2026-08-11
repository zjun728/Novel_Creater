"""Ownership inventory and read-boundary DTOs for project package snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
import json
import re
from types import MappingProxyType

from backend.domain.bibles import BiblePayload
from backend.domain.chapter_outlines import ChapterOutline, DraftChapterOutline, EditableChapterOutlineContent
from backend.domain.contracts import CreationContractPayload
from backend.domain.finalization import FinalizationChangeSet, QualityFinding, change_set_payload
from backend.domain.json_contracts import canonical_hash
from backend.domain.planning import DraftPlanningAggregate, PlanningAggregate
from backend.domain.project_packages import PackageRecord, RECORD_FIELD_ALLOWLISTS, ProjectPackageBusy, ProjectPackageConflict, ProjectPackageInvalid, ProjectPackageNotFound, freeze_json_value
from backend.database import DatabaseSession
from backend.security.paths import UnsafeLocalPath, managed_corpus_storage_key


PROJECT_OWNED_TABLES = frozenset({
    "projects", "creative_seeds", "creative_seed_revisions", "creative_seed_heads",
    "project_seed_selection_revisions", "project_selected_seeds", "project_model_binding_revisions",
    "project_model_binding_items", "project_model_binding_heads", "market_analyses",
    "seed_inspiration_attempts", "seed_inspiration_requests", "asset_recommendation_attempts",
    "asset_recommendation_requests", "style_trial_attempts", "style_trial_requests",
    "story_engine_batches", "story_engine_options", "project_contract_drafts", "creation_contracts",
    "style_contracts", "project_contract_heads", "contract_confirmation_requests",
    "creation_contract_engine_refs", "style_contract_template_refs", "creation_contract_experience_refs",
    "creation_contract_corpus_refs", "creation_contract_corpus_fragment_refs", "project_bible_drafts",
    "bible_generation_attempts", "creation_bible_revisions", "project_bible_heads",
    "bible_confirmation_requests", "planning_drafts", "planning_generation_attempts", "planning_revisions",
    "project_planning_heads", "planning_confirmation_requests", "chapter_outline_drafts",
    "chapter_outline_generation_attempts", "chapter_outline_revisions", "project_chapter_outline_heads",
    "chapter_outline_confirmation_requests", "chapter_sessions", "working_drafts", "draft_operation_attempts",
    "draft_candidates", "working_draft_revisions", "draft_operation_events", "candidate_freeze_requests",
    "candidate_quality_reports", "finalization_change_sets", "finalization_change_set_revisions",
    "finalization_records", "final_chapters", "canon_entities", "entity_aliases", "canon_revisions",
    "canon_events", "reference_uses",
})

SHARED_EXCLUDED_TABLES = frozenset({
    "provider_profiles", "provider_profile_mutation_requests", "application_settings", "style_templates",
    "style_template_heads", "experience_cards", "experience_card_heads", "corpus_blobs", "corpus_sources",
    "corpus_source_revisions", "corpus_source_heads", "corpus_chapters", "corpus_fragments",
    "corpus_import_runs", "corpus_source_deletions", "market_sources", "market_source_policy_revisions",
    "market_source_policy_heads", "market_snapshots", "market_snapshot_entries", "market_snapshot_manifests",
    "market_source_refresh_states", "market_refresh_requests",
})

INTERNAL_NON_PACKAGE_TABLES = frozenset({
    "schema_metadata", "current_state_projections", "memory_views", "arc_projections", "plot_thread_projections",
    "projection_heads", "project_package_import_commands", "project_import_provenance",
})

# Each project-owned table has an intentionally direct or normalized package record identity.
# Request/attempt pairs share inert history types so no command can be replayed on import.
PROJECT_TABLE_RECORD_TYPES: Mapping[str, str] = MappingProxyType({
    "projects": "project", "creative_seeds": "creative-seed", "creative_seed_revisions": "creative-seed-revision",
    "creative_seed_heads": "creative-seed-head", "project_seed_selection_revisions": "project-seed-selection-revision",
    "project_selected_seeds": "project-selected-seed", "project_model_binding_revisions": "project-model-binding-revision",
    "project_model_binding_items": "project-model-binding-item", "project_model_binding_heads": "project-model-binding-head",
    "market_analyses": "market-analysis", "seed_inspiration_attempts": "seed-inspiration-history",
    "seed_inspiration_requests": "seed-inspiration-history", "asset_recommendation_attempts": "asset-recommendation-history",
    "asset_recommendation_requests": "asset-recommendation-history", "style_trial_attempts": "style-trial-history",
    "style_trial_requests": "style-trial-history", "story_engine_batches": "story-engine-batch",
    "story_engine_options": "story-engine-option", "project_contract_drafts": "project-contract-draft",
    "creation_contracts": "creation-contract", "style_contracts": "style-contract",
    "project_contract_heads": "project-contract-head", "contract_confirmation_requests": "contract-confirmation",
    "creation_contract_engine_refs": "creation-contract-engine-ref", "style_contract_template_refs": "style-contract-template-ref",
    "creation_contract_experience_refs": "creation-contract-experience-ref", "creation_contract_corpus_refs": "creation-contract-corpus-ref",
    "creation_contract_corpus_fragment_refs": "creation-contract-corpus-fragment-ref", "project_bible_drafts": "project-bible-draft",
    "bible_generation_attempts": "bible-generation-history", "creation_bible_revisions": "creation-bible-revision",
    "project_bible_heads": "project-bible-head", "bible_confirmation_requests": "bible-confirmation",
    "planning_drafts": "planning-draft", "planning_generation_attempts": "planning-generation-history",
    "planning_revisions": "planning-revision", "project_planning_heads": "project-planning-head",
    "planning_confirmation_requests": "planning-confirmation", "chapter_outline_drafts": "chapter-outline-draft",
    "chapter_outline_generation_attempts": "chapter-outline-generation-history", "chapter_outline_revisions": "chapter-outline-revision",
    "project_chapter_outline_heads": "project-chapter-outline-head", "chapter_outline_confirmation_requests": "chapter-outline-confirmation",
    "chapter_sessions": "chapter", "working_drafts": "working-draft", "draft_operation_attempts": "operation",
    "draft_candidates": "draft-candidate", "working_draft_revisions": "working-draft-revision",
    "draft_operation_events": "operation-event", "candidate_freeze_requests": "candidate-freeze",
    "candidate_quality_reports": "candidate-quality", "finalization_change_sets": "finalization-change-set",
    "finalization_change_set_revisions": "finalization-change-set-revision", "finalization_records": "finalization-record",
    "final_chapters": "final-chapter", "canon_entities": "canon-entity", "entity_aliases": "entity-alias",
    "canon_revisions": "canon-revision", "canon_events": "canon-event", "reference_uses": "reference-use",
})

NORMALIZED_SHARED_RECORD_TYPES: Mapping[str, str] = MappingProxyType({
    "style_templates": "asset", "experience_cards": "asset", "corpus_source_revisions": "corpus-revision",
})
FROZEN_CORPUS_BLOB_TABLES = frozenset({"corpus_blobs"})
LOGICAL_REFERENCE_TARGETS: Mapping[tuple[str, str], str] = MappingProxyType({
    ("chapter_outline_drafts", "source_attempt_id"): "chapter_outline_generation_attempts",
    ("chapter_sessions", "active_draft_operation_id"): "draft_operation_attempts",
    ("planning_drafts", "source_attempt_id"): "planning_generation_attempts",
})


PROJECT_TABLE_COLUMN_POLICIES = MappingProxyType({
    table: MappingProxyType(policy)
    for table, policy in {'asset_recommendation_attempts': {'binding_hash': 'public_field',
                                       'binding_revision_id': 'logical_reference',
                                       'completed_at': 'public_field',
                                       'created_at': 'public_field',
                                       'id': 'derived',
                                       'input_manifest_hash': 'excluded_sensitive_operational',
                                       'input_manifest_json': 'excluded_sensitive_operational',
                                       'project_id': 'derived',
                                       'public_error_code': 'normalized_inert_evidence',
                                       'result_hash': 'normalized_inert_evidence',
                                       'result_json': 'public_field',
                                       'selection_revision': 'public_field',
                                       'status': 'normalized_inert_evidence'},
     'asset_recommendation_requests': {'attempt_id': 'logical_reference',
                                       'completed_at': 'public_field',
                                       'created_at': 'public_field',
                                       'id': 'derived',
                                       'idempotency_key': 'excluded_sensitive_operational',
                                       'project_id': 'derived',
                                       'public_error_code': 'normalized_inert_evidence',
                                       'request_hash': 'normalized_inert_evidence',
                                       'result_hash': 'normalized_inert_evidence',
                                       'status': 'normalized_inert_evidence'},
     'bible_confirmation_requests': {'bible_revision_id': 'logical_reference',
                                     'completed_at': 'public_field',
                                     'contract_revision': 'public_field',
                                     'created_at': 'public_field',
                                     'creation_contract_id': 'logical_reference',
                                     'creation_hash': 'public_field',
                                     'draft_hash': 'public_field',
                                     'draft_id': 'logical_reference',
                                     'draft_version': 'public_field',
                                     'id': 'derived',
                                     'idempotency_key': 'excluded_sensitive_operational',
                                     'project_id': 'derived',
                                     'public_error_code': 'normalized_inert_evidence',
                                     'request_hash': 'normalized_inert_evidence',
                                     'result_hash': 'normalized_inert_evidence',
                                     'result_revision': 'public_field',
                                     'selection_revision': 'public_field',
                                     'status': 'normalized_inert_evidence',
                                     'style_contract_id': 'logical_reference',
                                     'style_hash': 'public_field'},
     'bible_generation_attempts': {'attempt_version': 'public_field',
                                   'binding_hash': 'public_field',
                                   'binding_revision_id': 'logical_reference',
                                   'completed_at': 'public_field',
                                   'contract_revision': 'public_field',
                                   'created_at': 'public_field',
                                   'creation_contract_id': 'logical_reference',
                                   'creation_hash': 'public_field',
                                   'id': 'derived',
                                   'idempotency_key': 'excluded_sensitive_operational',
                                   'input_manifest_hash': 'excluded_sensitive_operational',
                                   'input_manifest_json': 'excluded_sensitive_operational',
                                   'lease_expires_at': 'excluded_sensitive_operational',
                                   'model_name_snapshot': 'normalized_inert_evidence',
                                   'owner_token': 'excluded_sensitive_operational',
                                   'policy_version': 'public_field',
                                   'project_id': 'derived',
                                   'provider_id': 'excluded_sensitive_operational',
                                   'public_error_code': 'normalized_inert_evidence',
                                   'request_hash': 'normalized_inert_evidence',
                                   'result_hash': 'normalized_inert_evidence',
                                   'result_json': 'public_field',
                                   'seed_hash': 'public_field',
                                   'seed_id': 'logical_reference',
                                   'seed_revision_id': 'logical_reference',
                                   'selection_revision': 'public_field',
                                   'status': 'normalized_inert_evidence',
                                   'style_contract_id': 'logical_reference',
                                   'style_hash': 'public_field'},
     'candidate_freeze_requests': {'chapter_session_id': 'logical_reference',
                                   'created_at': 'public_field',
                                   'draft_candidate_id': 'logical_reference',
                                   'id': 'derived',
                                   'idempotency_key': 'excluded_sensitive_operational',
                                   'project_id': 'derived',
                                   'request_hash': 'normalized_inert_evidence'},
     'candidate_quality_reports': {'candidate_hash': 'public_field',
                                   'chapter_session_id': 'logical_reference',
                                   'content_hash': 'public_field',
                                   'context_manifest_hash': 'public_field',
                                   'created_at': 'public_field',
                                   'deterministic_blocks_json': 'public_field',
                                   'draft_candidate_id': 'logical_reference',
                                   'expected_canon_revision': 'public_field',
                                   'expected_outline_hash': 'public_field',
                                   'expected_planning_hash': 'public_field',
                                   'findings_json': 'public_field',
                                   'id': 'derived',
                                   'model_name_snapshot': 'normalized_inert_evidence',
                                   'policy_version': 'public_field',
                                   'project_id': 'derived',
                                   'provider_id': 'excluded_sensitive_operational',
                                   'provider_profile_revision': 'public_field',
                                   'status': 'normalized_inert_evidence'},
     'canon_entities': {'canonical_name': 'public_field',
                        'created_at': 'public_field',
                        'created_revision': 'public_field',
                        'entity_type': 'public_field',
                        'id': 'derived',
                        'normalized_name': 'public_field',
                        'project_id': 'derived'},
     'canon_events': {'assertion_operator': 'public_field',
                      'confirmation_status': 'public_field',
                      'created_at': 'public_field',
                      'effective_end_chapter': 'public_field',
                      'effective_start_chapter': 'public_field',
                      'entity_id': 'logical_reference',
                      'event_order': 'public_field',
                      'evidence_json': 'public_field',
                      'fact_kind': 'public_field',
                      'field_path': 'public_field',
                      'id': 'derived',
                      'project_id': 'derived',
                      'revision_id': 'logical_reference',
                      'revision_number': 'public_field',
                      'value_cardinality': 'public_field',
                      'value_json': 'public_field'},
     'canon_revisions': {'content_hash': 'public_field',
                         'created_at': 'public_field',
                         'id': 'derived',
                         'idempotency_key': 'excluded_sensitive_operational',
                         'parent_revision_number': 'public_field',
                         'project_id': 'derived',
                         'revision_number': 'public_field',
                         'source_id': 'logical_reference',
                         'source_type': 'public_field'},
     'chapter_outline_confirmation_requests': {'canon_revision': 'public_field',
                                               'chapter_num': 'public_field',
                                               'chapter_outline_draft_id': 'logical_reference',
                                               'completed_at': 'public_field',
                                               'created_at': 'public_field',
                                               'draft_hash': 'public_field',
                                               'draft_revision': 'public_field',
                                               'expected_head_revision': 'public_field',
                                               'id': 'derived',
                                               'idempotency_key': 'excluded_sensitive_operational',
                                               'outline_revision_id': 'logical_reference',
                                               'planning_hash': 'public_field',
                                               'planning_revision': 'public_field',
                                               'planning_revision_id': 'logical_reference',
                                               'project_id': 'derived',
                                               'projection_hash': 'public_field',
                                               'projection_revision': 'public_field',
                                               'public_error_code': 'normalized_inert_evidence',
                                               'request_fingerprint': 'normalized_inert_evidence',
                                               'result_hash': 'normalized_inert_evidence',
                                               'result_revision': 'public_field',
                                               'status': 'normalized_inert_evidence'},
     'chapter_outline_drafts': {'active_slot': 'excluded_sensitive_operational',
                                'base_head_revision': 'public_field',
                                'canon_revision': 'public_field',
                                'chapter_num': 'public_field',
                                'content_hash': 'public_field',
                                'content_json': 'public_field',
                                'created_at': 'public_field',
                                'draft_revision': 'public_field',
                                'id': 'derived',
                                'planning_hash': 'public_field',
                                'planning_revision': 'public_field',
                                'planning_revision_id': 'logical_reference',
                                'project_id': 'derived',
                                'projection_hash': 'public_field',
                                'projection_revision': 'public_field',
                                'source_attempt_id': 'logical_reference',
                                'status': 'normalized_inert_evidence',
                                'updated_at': 'public_field'},
     'chapter_outline_generation_attempts': {'active_slot': 'excluded_sensitive_operational',
                                             'binding_hash': 'public_field',
                                             'binding_revision': 'public_field',
                                             'binding_revision_id': 'logical_reference',
                                             'created_at': 'public_field',
                                             'failure_code': 'public_field',
                                             'fencing_token': 'excluded_sensitive_operational',
                                             'id': 'derived',
                                             'idempotency_key': 'excluded_sensitive_operational',
                                             'input_manifest_hash': 'excluded_sensitive_operational',
                                             'input_manifest_json': 'excluded_sensitive_operational',
                                             'lease_expires_at': 'excluded_sensitive_operational',
                                             'loaded_at': 'public_field',
                                             'loaded_outline_draft_revision': 'public_field',
                                             'model_name_snapshot': 'normalized_inert_evidence',
                                             'operation_id': 'logical_reference',
                                             'outline_draft_id': 'logical_reference',
                                             'project_id': 'derived',
                                             'provider_id': 'excluded_sensitive_operational',
                                             'request_fingerprint': 'normalized_inert_evidence',
                                             'result_content_hash': 'public_field',
                                             'result_content_json': 'public_field',
                                             'status': 'normalized_inert_evidence',
                                             'updated_at': 'public_field'},
     'chapter_outline_revisions': {'canon_revision': 'public_field',
                                   'chapter_num': 'public_field',
                                   'content_hash': 'public_field',
                                   'content_json': 'public_field',
                                   'created_at': 'public_field',
                                   'id': 'derived',
                                   'parent_revision': 'public_field',
                                   'planning_hash': 'public_field',
                                   'planning_revision': 'public_field',
                                   'planning_revision_id': 'logical_reference',
                                   'project_id': 'derived',
                                   'projection_hash': 'public_field',
                                   'projection_revision': 'public_field',
                                   'revision': 'public_field'},
     'chapter_sessions': {'active_draft_operation_id': 'logical_reference',
                          'chapter_num': 'public_field',
                          'chapter_outline_hash': 'public_field',
                          'chapter_outline_revision': 'public_field',
                          'chapter_outline_revision_id': 'logical_reference',
                          'created_at': 'public_field',
                          'draft_operation_fencing_token': 'excluded_sensitive_operational',
                          'expected_canon_revision': 'public_field',
                          'finalized_at': 'public_field',
                          'id': 'derived',
                          'planning_hash': 'public_field',
                          'planning_revision': 'public_field',
                          'planning_revision_id': 'logical_reference',
                          'project_id': 'derived',
                          'status': 'normalized_inert_evidence',
                          'story_block_hash': 'public_field',
                          'story_block_id': 'logical_reference',
                          'story_block_revision': 'public_field'},
     'contract_confirmation_requests': {'completed_at': 'public_field',
                                        'created_at': 'public_field',
                                        'creation_contract_id': 'logical_reference',
                                        'id': 'derived',
                                        'idempotency_key': 'excluded_sensitive_operational',
                                        'project_id': 'derived',
                                        'public_error_code': 'normalized_inert_evidence',
                                        'request_hash': 'normalized_inert_evidence',
                                        'result_revision': 'public_field',
                                        'selection_revision': 'public_field',
                                        'status': 'normalized_inert_evidence',
                                        'style_contract_id': 'logical_reference'},
     'creation_bible_revisions': {'binding_hash': 'public_field',
                                  'binding_revision_id': 'logical_reference',
                                  'confirmed_at': 'public_field',
                                  'content_hash': 'public_field',
                                  'content_json': 'public_field',
                                  'contract_revision': 'public_field',
                                  'creation_contract_id': 'logical_reference',
                                  'creation_hash': 'public_field',
                                  'id': 'derived',
                                  'policy_version': 'public_field',
                                  'project_id': 'derived',
                                  'revision': 'public_field',
                                  'seed_hash': 'public_field',
                                  'seed_id': 'logical_reference',
                                  'seed_revision_id': 'logical_reference',
                                  'selection_revision': 'public_field',
                                  'style_contract_id': 'logical_reference',
                                  'style_hash': 'public_field'},
     'creation_contract_corpus_fragment_refs': {'chapter_char_end': 'public_field',
                                                'chapter_char_start': 'public_field',
                                                'corpus_chapter_id': 'logical_reference',
                                                'corpus_fragment_id': 'logical_reference',
                                                'corpus_source_id': 'logical_reference',
                                                'creation_contract_id': 'logical_reference',
                                                'fragment_hash': 'public_field',
                                                'reference_use': 'public_field',
                                                'sort_order': 'public_field',
                                                'source_hash': 'public_field',
                                                'source_revision': 'public_field'},
     'creation_contract_corpus_refs': {'corpus_source_id': 'logical_reference',
                                       'creation_contract_id': 'logical_reference',
                                       'selection_mode': 'public_field',
                                       'sort_order': 'public_field',
                                       'source_hash': 'public_field',
                                       'source_revision': 'public_field'},
     'creation_contract_engine_refs': {'creation_contract_id': 'logical_reference',
                                       'engine_hash': 'public_field',
                                       'engine_option_id': 'logical_reference',
                                       'project_id': 'derived'},
     'creation_contract_experience_refs': {'asset_hash': 'public_field',
                                           'asset_revision': 'public_field',
                                           'creation_contract_id': 'logical_reference',
                                           'experience_card_id': 'logical_reference',
                                           'sort_order': 'public_field'},
     'creation_contracts': {'binding_hash': 'public_field',
                            'binding_revision_id': 'logical_reference',
                            'channel_profile_key': 'public_field',
                            'chapter_capacity_policy': 'public_field',
                            'confirmed_at': 'public_field',
                            'content_hash': 'public_field',
                            'content_json': 'public_field',
                            'genre_profile_key': 'public_field',
                            'id': 'derived',
                            'project_id': 'derived',
                            'quality_charter_version': 'public_field',
                            'reference_manifest_hash': 'public_field',
                            'reference_manifest_json': 'public_field',
                            'revision': 'public_field',
                            'seed_hash': 'public_field',
                            'seed_id': 'logical_reference',
                            'seed_revision_id': 'logical_reference',
                            'selection_revision': 'public_field',
                            'total_word_max': 'public_field',
                            'total_word_min': 'public_field'},
     'creative_seed_heads': {'content_hash': 'public_field',
                             'revision': 'public_field',
                             'revision_id': 'logical_reference',
                             'seed_id': 'logical_reference',
                             'updated_at': 'public_field'},
     'creative_seed_revisions': {'content_hash': 'public_field',
                                 'created_at': 'public_field',
                                 'id': 'derived',
                                 'payload_json': 'public_field',
                                 'project_id': 'derived',
                                 'revision': 'public_field',
                                 'seed_id': 'logical_reference'},
     'creative_seeds': {'created_at': 'public_field',
                        'id': 'derived',
                        'project_id': 'derived',
                        'status': 'normalized_inert_evidence',
                        'updated_at': 'public_field'},
     'draft_candidates': {'basis_hash': 'public_field',
                          'chapter_session_id': 'logical_reference',
                          'content': 'public_field',
                          'content_hash': 'public_field',
                          'created_at': 'public_field',
                          'id': 'derived',
                          'project_id': 'derived',
                          'provenance_json': 'public_field',
                          'working_draft_revision': 'public_field'},
     'draft_operation_attempts': {'active_slot': 'excluded_sensitive_operational',
                                  'base_working_draft_hash': 'public_field',
                                  'base_working_draft_revision': 'public_field',
                                  'cancelled_at': 'public_field',
                                  'chapter_session_id': 'logical_reference',
                                  'completed_at': 'public_field',
                                  'created_at': 'public_field',
                                  'failure_code': 'public_field',
                                  'fencing_token': 'excluded_sensitive_operational',
                                  'heartbeat_at': 'public_field',
                                  'id': 'derived',
                                  'idempotency_key': 'excluded_sensitive_operational',
                                  'input_manifest_hash': 'excluded_sensitive_operational',
                                  'input_manifest_json': 'excluded_sensitive_operational',
                                  'last_event_sequence': 'public_field',
                                  'lease_expires_at': 'excluded_sensitive_operational',
                                  'model_name_snapshot': 'normalized_inert_evidence',
                                  'operation_type': 'public_field',
                                  'partial_output_hash': 'excluded_sensitive_operational',
                                  'partial_output_scalars': 'excluded_sensitive_operational',
                                  'partial_output_text': 'excluded_sensitive_operational',
                                  'project_id': 'derived',
                                  'provider_id': 'excluded_sensitive_operational',
                                  'request_fingerprint': 'normalized_inert_evidence',
                                  'result_content_hash': 'public_field',
                                  'result_working_draft_revision': 'public_field',
                                  'status': 'normalized_inert_evidence',
                                  'updated_at': 'public_field'},
     'draft_operation_events': {'closed_payload_json': 'excluded_sensitive_operational',
                                'created_at': 'public_field',
                                'draft_operation_id': 'logical_reference',
                                'event_type': 'public_field',
                                'id': 'derived',
                                'project_id': 'derived',
                                'sequence_num': 'public_field'},
     'entity_aliases': {'alias': 'public_field',
                        'created_at': 'public_field',
                        'created_revision': 'public_field',
                        'entity_id': 'logical_reference',
                        'id': 'derived',
                        'normalized_alias': 'public_field',
                        'project_id': 'derived'},
     'final_chapters': {'canon_revision': 'public_field',
                        'chapter_num': 'public_field',
                        'chapter_outline_hash': 'public_field',
                        'chapter_outline_revision': 'public_field',
                        'chapter_outline_revision_id': 'logical_reference',
                        'chapter_session_id': 'logical_reference',
                        'content': 'public_field',
                        'content_hash': 'public_field',
                        'draft_candidate_id': 'logical_reference',
                        'finalization_record_id': 'logical_reference',
                        'finalized_at': 'public_field',
                        'id': 'derived',
                        'planning_hash': 'public_field',
                        'planning_revision': 'public_field',
                        'planning_revision_id': 'logical_reference',
                        'project_id': 'derived',
                        'title': 'public_field'},
     'finalization_change_set_revisions': {'change_set_id': 'logical_reference',
                                           'content_hash': 'public_field',
                                           'created_at': 'public_field',
                                           'id': 'derived',
                                           'payload_json': 'public_field',
                                           'project_id': 'derived',
                                           'revision': 'public_field',
                                           'source': 'public_field'},
     'finalization_change_sets': {'active_slot': 'excluded_sensitive_operational',
                                  'candidate_hash': 'public_field',
                                  'chapter_session_id': 'logical_reference',
                                  'confirmed_at': 'public_field',
                                  'confirmed_revision': 'public_field',
                                  'confirmed_revision_hash': 'public_field',
                                  'context_manifest_hash': 'public_field',
                                  'context_manifest_json': 'public_field',
                                  'created_at': 'public_field',
                                  'current_revision': 'public_field',
                                  'current_revision_hash': 'public_field',
                                  'draft_candidate_id': 'logical_reference',
                                  'expected_canon_revision': 'public_field',
                                  'expected_outline_hash': 'public_field',
                                  'expected_planning_hash': 'public_field',
                                  'extraction_id': 'logical_reference',
                                  'id': 'derived',
                                  'idempotency_key': 'excluded_sensitive_operational',
                                  'project_id': 'derived',
                                  'quality_report_id': 'logical_reference',
                                  'request_fingerprint': 'normalized_inert_evidence',
                                  'status': 'normalized_inert_evidence',
                                  'updated_at': 'public_field'},
     'finalization_records': {'candidate_hash': 'public_field',
                              'change_set_hash': 'public_field',
                              'change_set_id': 'logical_reference',
                              'change_set_revision': 'public_field',
                              'chapter_session_id': 'logical_reference',
                              'committed_canon_revision': 'public_field',
                              'draft_candidate_id': 'logical_reference',
                              'expected_canon_revision': 'public_field',
                              'finalized_at': 'public_field',
                              'id': 'derived',
                              'idempotency_key': 'excluded_sensitive_operational',
                              'project_id': 'derived',
                              'request_fingerprint': 'normalized_inert_evidence',
                              'result_payload_json': 'public_field'},
     'market_analyses': {'analysis_json': 'public_field',
                         'binding_hash': 'public_field',
                         'binding_revision_id': 'logical_reference',
                         'completed_at': 'public_field',
                         'created_at': 'public_field',
                         'id': 'derived',
                         'idempotency_key': 'excluded_sensitive_operational',
                         'input_manifest_hash': 'excluded_sensitive_operational',
                         'input_manifest_json': 'excluded_sensitive_operational',
                         'policy_version': 'public_field',
                         'project_id': 'derived',
                         'public_error_code': 'normalized_inert_evidence',
                         'request_hash': 'normalized_inert_evidence',
                         'result_hash': 'normalized_inert_evidence',
                         'status': 'normalized_inert_evidence'},
     'planning_confirmation_requests': {'completed_at': 'public_field',
                                        'created_at': 'public_field',
                                        'draft_hash': 'public_field',
                                        'draft_revision': 'public_field',
                                        'expected_head_revision': 'public_field',
                                        'id': 'derived',
                                        'idempotency_key': 'excluded_sensitive_operational',
                                        'planning_draft_id': 'logical_reference',
                                        'planning_revision_id': 'logical_reference',
                                        'project_id': 'derived',
                                        'public_error_code': 'normalized_inert_evidence',
                                        'request_fingerprint': 'normalized_inert_evidence',
                                        'result_hash': 'normalized_inert_evidence',
                                        'result_revision': 'public_field',
                                        'status': 'normalized_inert_evidence'},
     'planning_drafts': {'active_slot': 'excluded_sensitive_operational',
                         'base_head_revision': 'public_field',
                         'bible_hash': 'public_field',
                         'bible_revision': 'public_field',
                         'bible_revision_id': 'logical_reference',
                         'content_hash': 'public_field',
                         'content_json': 'public_field',
                         'contract_revision': 'public_field',
                         'created_at': 'public_field',
                         'creation_contract_id': 'logical_reference',
                         'creation_hash': 'public_field',
                         'draft_revision': 'public_field',
                         'id': 'derived',
                         'project_id': 'derived',
                         'seed_hash': 'public_field',
                         'seed_id': 'logical_reference',
                         'seed_revision_id': 'logical_reference',
                         'selection_revision': 'public_field',
                         'source_attempt_id': 'logical_reference',
                         'status': 'normalized_inert_evidence',
                         'style_contract_id': 'logical_reference',
                         'style_hash': 'public_field',
                         'updated_at': 'public_field'},
     'planning_generation_attempts': {'active_slot': 'excluded_sensitive_operational',
                                      'binding_hash': 'public_field',
                                      'binding_revision': 'public_field',
                                      'binding_revision_id': 'logical_reference',
                                      'created_at': 'public_field',
                                      'draft_id': 'logical_reference',
                                      'failure_code': 'public_field',
                                      'fencing_token': 'excluded_sensitive_operational',
                                      'id': 'derived',
                                      'idempotency_key': 'excluded_sensitive_operational',
                                      'input_manifest_hash': 'excluded_sensitive_operational',
                                      'input_manifest_json': 'excluded_sensitive_operational',
                                      'lease_expires_at': 'excluded_sensitive_operational',
                                      'loaded_at': 'public_field',
                                      'loaded_draft_revision': 'public_field',
                                      'model_name_snapshot': 'normalized_inert_evidence',
                                      'operation_id': 'logical_reference',
                                      'project_id': 'derived',
                                      'provider_id': 'excluded_sensitive_operational',
                                      'request_fingerprint': 'normalized_inert_evidence',
                                      'result_content_hash': 'public_field',
                                      'result_content_json': 'public_field',
                                      'status': 'normalized_inert_evidence',
                                      'updated_at': 'public_field'},
     'planning_revisions': {'bible_hash': 'public_field',
                            'bible_revision': 'public_field',
                            'bible_revision_id': 'logical_reference',
                            'content_hash': 'public_field',
                            'content_json': 'public_field',
                            'contract_revision': 'public_field',
                            'created_at': 'public_field',
                            'creation_contract_id': 'logical_reference',
                            'creation_hash': 'public_field',
                            'id': 'derived',
                            'parent_revision': 'public_field',
                            'project_id': 'derived',
                            'revision': 'public_field',
                            'seed_hash': 'public_field',
                            'seed_id': 'logical_reference',
                            'seed_revision_id': 'logical_reference',
                            'selection_revision': 'public_field',
                            'style_contract_id': 'logical_reference',
                            'style_hash': 'public_field'},
     'project_bible_drafts': {'active_slot': 'excluded_sensitive_operational',
                              'base_head_revision': 'public_field',
                              'binding_hash': 'public_field',
                              'binding_revision_id': 'logical_reference',
                              'content_hash': 'public_field',
                              'contract_revision': 'public_field',
                              'created_at': 'public_field',
                              'creation_contract_id': 'logical_reference',
                              'creation_hash': 'public_field',
                              'draft_json': 'public_field',
                              'draft_version': 'public_field',
                              'id': 'derived',
                              'policy_version': 'public_field',
                              'project_id': 'derived',
                              'seed_hash': 'public_field',
                              'seed_id': 'logical_reference',
                              'seed_revision_id': 'logical_reference',
                              'selection_revision': 'public_field',
                              'style_contract_id': 'logical_reference',
                              'style_hash': 'public_field',
                              'updated_at': 'public_field'},
     'project_bible_heads': {'bible_revision_id': 'logical_reference',
                             'content_hash': 'public_field',
                             'project_id': 'derived',
                             'revision': 'public_field',
                             'updated_at': 'public_field'},
     'project_chapter_outline_heads': {'chapter_num': 'public_field',
                                       'content_hash': 'public_field',
                                       'outline_revision_id': 'logical_reference',
                                       'project_id': 'derived',
                                       'revision': 'public_field',
                                       'updated_at': 'public_field'},
     'project_contract_drafts': {'base_head_revision': 'public_field',
                                 'content_hash': 'public_field',
                                 'created_at': 'public_field',
                                 'draft_json': 'public_field',
                                 'draft_version': 'public_field',
                                 'engine_option_id': 'logical_reference',
                                 'id': 'derived',
                                 'project_id': 'derived',
                                 'seed_hash': 'public_field',
                                 'seed_revision_id': 'logical_reference',
                                 'selection_revision': 'public_field',
                                 'updated_at': 'public_field'},
     'project_contract_heads': {'creation_contract_id': 'logical_reference',
                                'creation_hash': 'public_field',
                                'project_id': 'derived',
                                'revision': 'public_field',
                                'style_contract_id': 'logical_reference',
                                'style_hash': 'public_field',
                                'updated_at': 'public_field'},
     'project_model_binding_heads': {'binding_revision_id': 'logical_reference',
                                     'content_hash': 'public_field',
                                     'project_id': 'derived',
                                     'revision': 'public_field',
                                     'updated_at': 'public_field'},
     'project_model_binding_items': {'binding_revision_id': 'logical_reference',
                                     'item_hash': 'public_field',
                                     'model_name_snapshot': 'normalized_inert_evidence',
                                     'provider_id': 'excluded_sensitive_operational',
                                     'provider_name_snapshot': 'public_field',
                                     'resolution_status': 'public_field',
                                     'task_key': 'public_field'},
     'project_model_binding_revisions': {'content_hash': 'public_field',
                                         'created_at': 'public_field',
                                         'id': 'derived',
                                         'project_id': 'derived',
                                         'revision': 'public_field',
                                         'source_project_id': 'logical_reference'},
     'project_planning_heads': {'content_hash': 'public_field',
                                'planning_revision_id': 'logical_reference',
                                'project_id': 'derived',
                                'revision': 'public_field',
                                'updated_at': 'public_field'},
     'project_seed_selection_revisions': {'project_id': 'derived',
                                          'seed_hash': 'public_field',
                                          'seed_id': 'logical_reference',
                                          'seed_revision_id': 'logical_reference',
                                          'selected_at': 'public_field',
                                          'selection_revision': 'public_field'},
     'project_selected_seeds': {'project_id': 'derived',
                                'seed_hash': 'public_field',
                                'seed_id': 'logical_reference',
                                'seed_revision_id': 'logical_reference',
                                'selected_at': 'public_field',
                                'selection_revision': 'public_field',
                                'updated_at': 'public_field'},
     'projects': {'archived_at': 'public_field',
                  'created_at': 'public_field',
                  'current_chapter': 'public_field',
                  'description': 'public_field',
                  'genre': 'public_field',
                  'id': 'derived',
                  'lifecycle_revision': 'public_field',
                  'status': 'normalized_inert_evidence',
                  'target_chapters': 'public_field',
                  'target_words': 'public_field',
                  'title': 'public_field',
                  'updated_at': 'public_field'},
     'reference_uses': {'chapter_session_id': 'logical_reference',
                        'corpus_chapter_id': 'logical_reference',
                        'corpus_source_id': 'logical_reference',
                        'created_at': 'public_field',
                        'draft_candidate_id': 'logical_reference',
                        'id': 'derived',
                        'location_end': 'public_field',
                        'location_start': 'public_field',
                        'project_id': 'derived',
                        'reference_purpose': 'public_field',
                        'referenced_text_hash': 'public_field'},
     'seed_inspiration_attempts': {'binding_hash': 'public_field',
                                   'binding_revision_id': 'logical_reference',
                                   'completed_at': 'public_field',
                                   'created_at': 'public_field',
                                   'id': 'derived',
                                   'input_manifest_hash': 'excluded_sensitive_operational',
                                   'input_manifest_json': 'excluded_sensitive_operational',
                                   'market_analysis_hash': 'public_field',
                                   'market_analysis_id': 'logical_reference',
                                   'market_snapshot_hash': 'public_field',
                                   'market_snapshot_id': 'logical_reference',
                                   'market_source_id': 'logical_reference',
                                   'project_id': 'derived',
                                   'public_error_code': 'normalized_inert_evidence',
                                   'result_hash': 'normalized_inert_evidence',
                                   'result_json': 'public_field',
                                   'selection_revision': 'public_field',
                                   'status': 'normalized_inert_evidence'},
     'seed_inspiration_requests': {'attempt_id': 'logical_reference',
                                   'completed_at': 'public_field',
                                   'created_at': 'public_field',
                                   'id': 'derived',
                                   'idempotency_key': 'excluded_sensitive_operational',
                                   'project_id': 'derived',
                                   'public_error_code': 'normalized_inert_evidence',
                                   'request_hash': 'normalized_inert_evidence',
                                   'result_hash': 'normalized_inert_evidence',
                                   'status': 'normalized_inert_evidence'},
     'story_engine_batches': {'attempt_id': 'logical_reference',
                              'attempt_started_at': 'public_field',
                              'binding_hash': 'public_field',
                              'binding_revision_id': 'logical_reference',
                              'created_at': 'public_field',
                              'finished_at': 'public_field',
                              'id': 'derived',
                              'idempotency_key': 'excluded_sensitive_operational',
                              'lease_expires_at': 'excluded_sensitive_operational',
                              'model_name_snapshot': 'normalized_inert_evidence',
                              'project_id': 'derived',
                              'provider_id': 'excluded_sensitive_operational',
                              'public_error_code': 'normalized_inert_evidence',
                              'raw_response_hash': 'excluded_sensitive_operational',
                              'raw_response_text': 'excluded_sensitive_operational',
                              'request_hash': 'normalized_inert_evidence',
                              'request_json': 'excluded_sensitive_operational',
                              'seed_hash': 'public_field',
                              'seed_id': 'logical_reference',
                              'seed_revision_id': 'logical_reference',
                              'selection_revision': 'public_field',
                              'source_type': 'public_field',
                              'status': 'normalized_inert_evidence'},
     'story_engine_options': {'batch_id': 'logical_reference',
                              'content_hash': 'public_field',
                              'created_at': 'public_field',
                              'id': 'derived',
                              'option_order': 'public_field',
                              'payload_json': 'public_field',
                              'project_id': 'derived',
                              'selection_revision': 'public_field'},
     'style_contract_template_refs': {'asset_hash': 'public_field',
                                      'asset_revision': 'public_field',
                                      'role': 'public_field',
                                      'sort_order': 'public_field',
                                      'style_contract_id': 'logical_reference',
                                      'style_template_id': 'logical_reference'},
     'style_contracts': {'confirmed_at': 'public_field',
                         'content_hash': 'public_field',
                         'creation_contract_id': 'logical_reference',
                         'dislikes_json': 'public_field',
                         'id': 'derived',
                         'likes_json': 'public_field',
                         'merged_style_json': 'public_field',
                         'project_id': 'derived',
                         'revision': 'public_field'},
     'style_trial_attempts': {'binding_hash': 'public_field',
                              'binding_revision_id': 'logical_reference',
                              'completed_at': 'public_field',
                              'created_at': 'public_field',
                              'id': 'derived',
                              'input_manifest_hash': 'excluded_sensitive_operational',
                              'input_manifest_json': 'excluded_sensitive_operational',
                              'project_id': 'derived',
                              'public_error_code': 'normalized_inert_evidence',
                              'result_hash': 'normalized_inert_evidence',
                              'result_json': 'public_field',
                              'selection_revision': 'public_field',
                              'status': 'normalized_inert_evidence'},
     'style_trial_requests': {'attempt_id': 'logical_reference',
                              'completed_at': 'public_field',
                              'created_at': 'public_field',
                              'id': 'derived',
                              'idempotency_key': 'excluded_sensitive_operational',
                              'project_id': 'derived',
                              'public_error_code': 'normalized_inert_evidence',
                              'request_hash': 'normalized_inert_evidence',
                              'result_hash': 'normalized_inert_evidence',
                              'status': 'normalized_inert_evidence'},
     'working_draft_revisions': {'chapter_session_id': 'logical_reference',
                                 'content': 'public_field',
                                 'content_hash': 'public_field',
                                 'created_at': 'public_field',
                                 'id': 'derived',
                                 'project_id': 'derived',
                                 'replacement_reason': 'public_field',
                                 'snapshot_role': 'public_field',
                                 'source_candidate_id': 'logical_reference',
                                 'source_operation_id': 'logical_reference',
                                 'working_draft_id': 'logical_reference',
                                 'working_draft_revision': 'public_field'},
     'working_drafts': {'chapter_session_id': 'logical_reference',
                        'content': 'public_field',
                        'content_hash': 'public_field',
                        'id': 'derived',
                        'project_id': 'derived',
                        'revision': 'public_field',
                        'source_payload_json': 'public_field',
                        'updated_at': 'public_field'}}.items()
})

@dataclass(frozen=True, slots=True)
class OwnershipJoin:
    child_table: str
    child_column: str
    parent_table: str
    parent_column: str = "id"


@dataclass(frozen=True, slots=True)
class OwnedQueryPlan:
    table: str
    sql: str
    selected_columns: tuple[str, ...]
    order_columns: tuple[str, ...]
    scope_table: str
    scope_column: str
    ownership_joins: tuple[OwnershipJoin, ...] = ()

_NON_PACKAGE_REFERENCE_COLUMNS = frozenset({
    ("seed_inspiration_attempts", "market_source_id"), ("seed_inspiration_attempts", "market_snapshot_id"),
    ("creation_contract_corpus_refs", "corpus_source_id"),
    ("creation_contract_corpus_fragment_refs", "corpus_source_id"),
    ("creation_contract_corpus_fragment_refs", "corpus_chapter_id"),
    ("creation_contract_corpus_fragment_refs", "corpus_fragment_id"),
    ("reference_uses", "corpus_source_id"), ("reference_uses", "corpus_chapter_id"),
})
_policy_copy = {table: dict(policy) for table, policy in PROJECT_TABLE_COLUMN_POLICIES.items()}
for _table, _column in _NON_PACKAGE_REFERENCE_COLUMNS:
    _policy_copy[_table][_column] = "normalized_inert_evidence"
_policy_copy["finalization_change_sets"]["extraction_id"] = "excluded_sensitive_operational"
PROJECT_TABLE_COLUMN_POLICIES = MappingProxyType({
    table: MappingProxyType(policy) for table, policy in _policy_copy.items()
})

_policy_copy = {table: dict(policy) for table, policy in PROJECT_TABLE_COLUMN_POLICIES.items()}
for _table, _column in {
    ("planning_generation_attempts", "operation_id"),
    ("chapter_outline_generation_attempts", "operation_id"),
    ("story_engine_batches", "attempt_id"),
}:
    _policy_copy[_table][_column] = "excluded_sensitive_operational"
_policy_copy["chapter_sessions"]["story_block_id"] = "nested_logical_reference"
_policy_copy["canon_revisions"]["source_id"] = "polymorphic_logical_reference"
_policy_copy["project_model_binding_revisions"]["source_project_id"] = "normalized_inert_evidence"
PROJECT_TABLE_COLUMN_POLICIES = MappingProxyType({
    table: MappingProxyType(policy) for table, policy in _policy_copy.items()
})
NESTED_LOGICAL_REFERENCE_TARGETS: Mapping[tuple[str, str], str] = MappingProxyType({
    ("chapter_sessions", "story_block_id"): "story-block",
})
POLYMORPHIC_LOGICAL_REFERENCE_TARGETS: Mapping[tuple[str, str], Mapping[str, str | None]] = MappingProxyType({
    ("canon_revisions", "source_id"): MappingProxyType({
        "bootstrap": None, "finalization": "finalization_change_sets", "manual_test": None,
    }),
})


_INDIRECT_OWNERSHIP_JOINS: Mapping[str, OwnershipJoin] = MappingProxyType({
    "creative_seed_heads": OwnershipJoin(
        "creative_seed_heads", "revision_id", "creative_seed_revisions"
    ),
    "project_model_binding_items": OwnershipJoin(
        "project_model_binding_items", "binding_revision_id", "project_model_binding_revisions"
    ),
    "style_contract_template_refs": OwnershipJoin(
        "style_contract_template_refs", "style_contract_id", "style_contracts"
    ),
    "creation_contract_experience_refs": OwnershipJoin(
        "creation_contract_experience_refs", "creation_contract_id", "creation_contracts"
    ),
    "creation_contract_corpus_refs": OwnershipJoin(
        "creation_contract_corpus_refs", "creation_contract_id", "creation_contracts"
    ),
    "creation_contract_corpus_fragment_refs": OwnershipJoin(
        "creation_contract_corpus_fragment_refs", "creation_contract_id", "creation_contracts"
    ),
})

_ORDER_COLUMNS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "creation_contract_corpus_fragment_refs": (
        "creation_contract_id", "sort_order", "corpus_fragment_id", "chapter_char_start", "chapter_char_end"
    ),
    "creation_contract_corpus_refs": ("creation_contract_id", "sort_order", "corpus_source_id"),
    "creation_contract_engine_refs": ("creation_contract_id",),
    "creation_contract_experience_refs": ("creation_contract_id", "sort_order", "experience_card_id"),
    "creative_seed_heads": ("seed_id",),
    "project_bible_heads": ("project_id",),
    "project_chapter_outline_heads": ("project_id", "chapter_num"),
    "project_contract_heads": ("project_id",),
    "project_model_binding_heads": ("project_id",),
    "project_model_binding_items": ("binding_revision_id", "task_key"),
    "project_planning_heads": ("project_id",),
    "project_seed_selection_revisions": ("project_id", "selection_revision"),
    "project_selected_seeds": ("project_id", "selection_revision"),
    "style_contract_template_refs": ("style_contract_id", "role"),
})


def _owned_query_plan(table: str) -> OwnedQueryPlan:
    selected_columns = tuple(sorted(
        column
        for column, category in PROJECT_TABLE_COLUMN_POLICIES[table].items()
        if category != "excluded_sensitive_operational"
    ))
    order_columns = _ORDER_COLUMNS.get(table, ("id",))
    join = _INDIRECT_OWNERSHIP_JOINS.get(table)
    ownership_joins = (join,) if join is not None else ()
    scope_table = join.parent_table if join is not None else table
    scope_alias = "t1" if join is not None else "t0"
    scope_column = "id" if table == "projects" else "project_id"
    select_sql = ",".join(f"t0.{column} AS {column}" for column in selected_columns)
    from_sql = f"FROM {table} t0"
    if join is not None:
        from_sql += (
            f" JOIN {join.parent_table} t1"
            f" ON t0.{join.child_column}=t1.{join.parent_column}"
        )
    order_sql = ",".join(f"t0.{column}" for column in order_columns)
    return OwnedQueryPlan(
        table=table,
        sql=f"SELECT {select_sql} {from_sql} WHERE {scope_alias}.{scope_column}=%s ORDER BY {order_sql}",
        selected_columns=selected_columns,
        order_columns=order_columns,
        scope_table=scope_table,
        scope_column=scope_column,
        ownership_joins=ownership_joins,
    )


PROJECT_OWNED_QUERY_PLANS: Mapping[str, OwnedQueryPlan] = MappingProxyType({
    table: _owned_query_plan(table) for table in sorted(PROJECT_OWNED_TABLES)
})


_REFERENCE_TARGET_BY_COLUMN: Mapping[str, str] = MappingProxyType({
    "active_draft_operation_id": "draft_operation_attempts",
    "batch_id": "story_engine_batches",
    "bible_revision_id": "creation_bible_revisions",
    "binding_revision_id": "project_model_binding_revisions",
    "change_set_id": "finalization_change_sets",
    "chapter_outline_draft_id": "chapter_outline_drafts",
    "chapter_outline_revision_id": "chapter_outline_revisions",
    "chapter_session_id": "chapter_sessions",
    "creation_contract_id": "creation_contracts",
    "draft_candidate_id": "draft_candidates",
    "draft_operation_id": "draft_operation_attempts",
    "engine_option_id": "story_engine_options",
    "entity_id": "canon_entities",
    "experience_card_id": "experience_cards",
    "finalization_record_id": "finalization_records",
    "market_analysis_id": "market_analyses",
    "outline_draft_id": "chapter_outline_drafts",
    "outline_revision_id": "chapter_outline_revisions",
    "planning_draft_id": "planning_drafts",
    "planning_revision_id": "planning_revisions",
    "quality_report_id": "candidate_quality_reports",
    "seed_id": "creative_seeds",
    "seed_revision_id": "creative_seed_revisions",
    "source_candidate_id": "draft_candidates",
    "source_operation_id": "draft_operation_attempts",
    "source_project_id": "projects",
    "style_contract_id": "style_contracts",
    "style_template_id": "style_templates",
    "working_draft_id": "working_drafts",
})
_REFERENCE_TARGET_OVERRIDES: Mapping[tuple[str, str], str] = MappingProxyType({
    ("asset_recommendation_requests", "attempt_id"): "asset_recommendation_attempts",
    ("bible_confirmation_requests", "draft_id"): "project_bible_drafts",
    ("canon_events", "revision_id"): "canon_revisions",
    ("chapter_outline_drafts", "source_attempt_id"): "chapter_outline_generation_attempts",
    ("chapter_outline_generation_attempts", "draft_id"): "chapter_outline_drafts",
    ("creative_seed_heads", "revision_id"): "creative_seed_revisions",
    ("planning_drafts", "source_attempt_id"): "planning_generation_attempts",
    ("planning_generation_attempts", "draft_id"): "planning_drafts",
    ("seed_inspiration_requests", "attempt_id"): "seed_inspiration_attempts",
    ("style_trial_requests", "attempt_id"): "style_trial_attempts",
})

_PROVIDER_PROFILE_QUERY = (
    "SELECT DISTINCT p.name AS provider_name,p.model_name AS model_name,"
    "p.api_key AS api_key,p.base_url AS base_url "
    "FROM provider_profiles p "
    "JOIN project_model_binding_items i ON i.provider_id=p.id "
    "JOIN project_model_binding_revisions r ON r.id=i.binding_revision_id "
    "WHERE r.project_id=%s "
    "ORDER BY p.name,p.model_name,p.api_key,p.base_url"
)
_MARKET_SNAPSHOT_EVIDENCE_QUERY = (
    "SELECT s.content_hash AS snapshot_hash,s.captured_at AS captured_at "
    "FROM market_snapshots s WHERE s.id=%s AND s.content_hash=%s ORDER BY s.id"
)

_FROZEN_ASSET_QUERIES: Mapping[str, str] = MappingProxyType({
    "experience_cards": (
        "SELECT id,stable_key,revision,title,category,payload_json,provenance_json,content_hash,status,created_at "
        "FROM experience_cards WHERE id=%s AND revision=%s AND content_hash=%s ORDER BY id"
    ),
    "style_templates": (
        "SELECT id,stable_key,revision,name,payload_json,provenance_json,content_hash,status,created_at "
        "FROM style_templates WHERE id=%s AND revision=%s AND content_hash=%s ORDER BY id"
    ),
})

_FROZEN_CORPUS_REVISION_QUERY = (
    "SELECT r.id,r.source_id,s.source_key,r.revision,r.content_hash,r.relative_path,r.display_name,"
    "r.author,r.reference_tags_json,r.notes,r.provenance_json,r.byte_length,r.encoding,"
    "r.parser_version,r.normalizer_version,r.fragmenter_version,r.index_version,r.status,"
    "r.imported_at,r.analyzed_at,r.created_at,b.byte_length AS blob_byte_length,b.storage_key "
    "FROM corpus_source_revisions r "
    "JOIN corpus_sources s ON s.id=r.source_id "
    "JOIN corpus_blobs b ON b.content_hash=r.content_hash "
    "WHERE r.source_id=%s AND r.revision=%s AND r.content_hash=%s ORDER BY r.id"
)
_REFERENCE_USE_CORPUS_REVISION_QUERY = (
    "SELECT r.source_id,r.revision,r.content_hash FROM corpus_chapters c "
    "JOIN corpus_source_revisions r ON r.id=c.source_revision_id "
    "WHERE c.corpus_source_id=%s AND c.id=%s ORDER BY r.id"
)
_FROZEN_CORPUS_CHAPTER_QUERY = (
    "SELECT c.id AS chapter_id,c.chapter_order,c.title,c.raw_byte_start,c.raw_byte_end,"
    "c.normalized_char_start,c.normalized_char_end,c.normalized_text,c.content_hash,c.created_at "
    "FROM corpus_chapters c WHERE c.corpus_source_id=%s AND c.source_revision_id=%s "
    "ORDER BY c.chapter_order,c.id"
)
_FROZEN_CORPUS_FRAGMENT_QUERY = (
    "SELECT f.id AS fragment_id,f.fragment_order,f.chapter_char_start,f.chapter_char_end,"
    "f.normalized_text,f.content_hash,f.analysis_version,f.index_payload,f.created_at "
    "FROM corpus_fragments f WHERE f.corpus_source_id=%s AND f.corpus_chapter_id=%s "
    "ORDER BY f.fragment_order,f.id"
)

_PROJECTION_QUERIES: Mapping[str, str] = MappingProxyType({
    "arcProjections": "SELECT content_hash FROM arc_projections WHERE project_id=%s ORDER BY revision_number,entity_id,arc_key,id",
    "currentStateProjections": "SELECT content_hash FROM current_state_projections WHERE project_id=%s ORDER BY revision_number,entity_id,field_path,id",
    "memoryViews": "SELECT content_hash FROM memory_views WHERE project_id=%s ORDER BY revision_number,subject_key,id",
    "plotThreadProjections": "SELECT content_hash FROM plot_thread_projections WHERE project_id=%s ORDER BY revision_number,subject_key,field_path,id",
    "projectionHeads": "SELECT content_hash FROM projection_heads WHERE project_id=%s ORDER BY project_id",
})


def _camel_case(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


def _json_value(value: object) -> object:
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    if isinstance(value, (Mapping, list, tuple)):
        return value
    raise _invalid()


def _public_field_name(column: str, allowlist: frozenset[str]) -> str | None:
    direct = _camel_case(column)
    aliases = {
        "chapter_num": "chapterNumber",
        "deterministic_blocks_json": "deterministicBlocks",
        "draft_json": "payload",
        "evidence_json": "evidence",
        "findings_json": "findings",
        "model_name_snapshot": "modelName",
        "operation_type": "operationKind",
        "payload_json": "payload",
        "provider_name_snapshot": "providerName",
        "request_hash": "requestFingerprint",
        "result_content_hash": "resultHash",
        "result_payload_json": "resultPayload",
        "sequence_num": "sequence",
        "source_payload_json": "payload",
        "value_json": "value",
    }
    candidates = (direct, aliases.get(column))
    if column == "content_json":
        candidates += ("payload", "content")
    if column == "result_content_json":
        candidates += ("payload",)
    for candidate in candidates:
        if candidate is not None and candidate in allowlist:
            return candidate
    return None


def _logical_field_name(table: str, column: str, allowlist: frozenset[str]) -> str | None:
    base = column.removesuffix("_id")
    aliases = {
        "chapter_session": "chapter",
        "draft_candidate": "candidate",
        "draft_operation": "operation",
    }
    base = aliases.get(base, base)
    candidate = _camel_case(base) + "LogicalId"
    if table == "canon_events" and column == "revision_id":
        candidate = "canonRevisionLogicalId"
    elif table == "working_draft_revisions" and column == "source_candidate_id":
        candidate = "candidateLogicalId"
    elif table == "working_draft_revisions" and column == "source_operation_id":
        candidate = "operationLogicalId"
    elif table in {"chapter_sessions", "final_chapters"} and column == "chapter_outline_revision_id":
        candidate = "outlineRevisionLogicalId"
    return candidate if candidate in allowlist else None


def _column_export_decision(table: str, column: str, category: str) -> str:
    if column == "confirmed_at" and table in {
        "creation_contracts", "style_contracts", "creation_bible_revisions",
    }:
        return "createdAt"
    allowlist = RECORD_FIELD_ALLOWLISTS[PROJECT_TABLE_RECORD_TYPES[table]]
    explicit = {
        ("bible_confirmation_requests", "result_hash"): "contentHash",
        ("planning_confirmation_requests", "planning_draft_id"): "draftLogicalId",
        ("planning_confirmation_requests", "result_hash"): "contentHash",
        ("chapter_outline_confirmation_requests", "chapter_outline_draft_id"): "draftLogicalId",
        ("chapter_outline_confirmation_requests", "result_hash"): "contentHash",
        ("creation_contract_engine_refs", "engine_hash"): "contentHash",
        ("creation_contract_engine_refs", "engine_option_id"): "storyEngineLogicalId",
        ("style_contract_template_refs", "asset_hash"): "contentHash",
        ("style_contract_template_refs", "style_template_id"): "@frozen-style-template",
        ("creation_contract_experience_refs", "asset_hash"): "contentHash",
        ("creation_contract_experience_refs", "experience_card_id"): "@frozen-experience-card",
        ("creation_contract_corpus_refs", "source_hash"): "contentHash",
        ("creation_contract_corpus_fragment_refs", "source_hash"): "@frozen-corpus-revision",
        ("creation_contract_corpus_fragment_refs", "fragment_hash"): "contentHash",
    }.get((table, column))
    if explicit is not None:
        return explicit
    if table == "project_model_binding_revisions" and column == "source_project_id":
        return "@binding-source"
    if table == "style_contracts" and column in {
        "merged_style_json", "likes_json", "dislikes_json",
    }:
        return "@style-contract-payload"
    if category in {"public_field", "normalized_inert_evidence"}:
        return _public_field_name(column, allowlist) or "@omit-normalized"
    if category == "logical_reference":
        return _logical_field_name(table, column, allowlist) or "@validate-logical"
    if category == "nested_logical_reference":
        return "storyBlockLogicalId"
    if category == "polymorphic_logical_reference":
        return "sourceLogicalId"
    raise RuntimeError("unclassified project package column")


PACKAGE_COLUMN_EXPORT_DECISIONS: Mapping[tuple[str, str], str] = MappingProxyType({
    (table, column): _column_export_decision(table, column, category)
    for table, policy in PROJECT_TABLE_COLUMN_POLICIES.items()
    for column, category in policy.items()
    if category not in {"derived", "excluded_sensitive_operational"}
})
_PACKAGE_COLUMN_EXPORT_DECISION_MANIFEST = "\n".join(
    f"{table}.{column}={decision}"
    for (table, column), decision in sorted(PACKAGE_COLUMN_EXPORT_DECISIONS.items())
)
PACKAGE_COLUMN_EXPORT_DECISION_FINGERPRINT = sha256(
    _PACKAGE_COLUMN_EXPORT_DECISION_MANIFEST.encode("utf-8")
).hexdigest()
if PACKAGE_COLUMN_EXPORT_DECISION_FINGERPRINT != (
    "67383ba721bd03d14b40d87214c489c46223bc4c2b708f586823fea508292c9f"
):
    raise RuntimeError("project package export decisions require an explicit audit")


def _reference_target(table: str, column: str) -> str:
    target = _REFERENCE_TARGET_OVERRIDES.get((table, column), _REFERENCE_TARGET_BY_COLUMN.get(column))
    if target is None:
        raise _invalid()
    return target


def _record_revision(row: Mapping[str, object]) -> int:
    for column in ("revision", "selection_revision", "draft_revision", "working_draft_revision"):
        value = row.get(column)
        if type(value) is int and value >= 0:
            return value
    return 0


def _record_order(row: Mapping[str, object]) -> int:
    for column in ("event_order", "option_order", "candidate_order", "sort_order", "sequence_num"):
        value = row.get(column)
        if type(value) is int and value >= 0:
            return value
    return 0


_BIBLE_ITEM_TYPES: Mapping[str, str] = MappingProxyType({
    "worldRules": "bible-world-rule",
    "coreCast": "bible-core-cast",
    "factions": "bible-faction",
    "longTermConflicts": "bible-long-term-conflict",
    "relationshipDynamics": "bible-relationship-dynamic",
    "continuityGuardrails": "bible-continuity-guardrail",
    "openDesignQuestions": "bible-open-design-question",
})


def _register_authority_id(
    identities: dict[tuple[str, object], str],
    counters: dict[str, int],
    kind: str,
    raw_id: object,
) -> str:
    if not isinstance(raw_id, str) or not raw_id:
        raise _invalid()
    identity_key = (kind, raw_id)
    existing = identities.get(identity_key)
    if existing is not None:
        return existing
    counters[kind] = counters.get(kind, 0) + 1
    logical_id = f"{kind}:{counters[kind]}"
    identities[identity_key] = logical_id
    return logical_id


def _authority_id(identities: Mapping[tuple[str, object], str], kind: str, raw_id: object) -> str:
    matched = identities.get((kind, raw_id))
    if matched is None:
        raise _invalid()
    return matched


def _planning_node_source_id(node: object) -> str:
    database_id = getattr(node, "id", None)
    client_key = getattr(node, "client_key", None)
    if database_id is not None:
        return database_id
    if client_key is not None:
        return client_key
    raise _invalid()


def _validate_planning_payload(table: str, value: object) -> PlanningAggregate | DraftPlanningAggregate:
    parsed = _json_value(value)
    if table == "planning_revisions":
        return PlanningAggregate.model_validate(parsed)
    try:
        return PlanningAggregate.model_validate(parsed)
    except ValueError:
        return DraftPlanningAggregate.model_validate(parsed)


def _register_planning_nodes(
    planning: PlanningAggregate | DraftPlanningAggregate,
    identities: dict[tuple[str, object], str],
    counters: dict[str, int],
) -> None:
    for node in planning.volumes:
        _register_authority_id(identities, counters, "planning-volume", _planning_node_source_id(node))
    for node in planning.plots:
        _register_authority_id(identities, counters, "planning-plot", _planning_node_source_id(node))
    for block in planning.story_blocks:
        _register_authority_id(identities, counters, "story-block", _planning_node_source_id(block))
        for stage in block.stages:
            _register_authority_id(identities, counters, "planning-stage", _planning_node_source_id(stage))
            for task in stage.scene_tasks:
                _register_authority_id(identities, counters, "scene-task", _planning_node_source_id(task))


def _rewrite_planning_payload(
    planning: PlanningAggregate | DraftPlanningAggregate,
    identities: Mapping[tuple[str, object], str],
) -> dict[str, object]:
    payload = planning.model_dump(mode="json", by_alias=True)

    def replace_definition(node: object, dumped: dict[str, object], kind: str) -> None:
        source_id = _planning_node_source_id(node)
        key = "id" if getattr(node, "id", None) is not None else "clientNodeKey"
        dumped[key] = _authority_id(identities, kind, source_id)

    for node, dumped in zip(planning.volumes, payload["volumes"], strict=True):
        replace_definition(node, dumped, "planning-volume")
    for node, dumped in zip(planning.plots, payload["plots"], strict=True):
        replace_definition(node, dumped, "planning-plot")
    for block, dumped_block in zip(planning.story_blocks, payload["storyBlocks"], strict=True):
        replace_definition(block, dumped_block, "story-block")
        if isinstance(planning, PlanningAggregate):
            dumped_block["volumeId"] = _authority_id(identities, "planning-volume", block.volume_id)
            dumped_block["plotIds"] = [
                _authority_id(identities, "planning-plot", plot_id) for plot_id in block.plot_ids
            ]
        else:
            dumped_block["volumeRef"] = _authority_id(identities, "planning-volume", block.volume_ref)
            dumped_block["plotRefs"] = [
                _authority_id(identities, "planning-plot", plot_id) for plot_id in block.plot_refs
            ]
        for stage, dumped_stage in zip(block.stages, dumped_block["stages"], strict=True):
            replace_definition(stage, dumped_stage, "planning-stage")
            if isinstance(planning, PlanningAggregate):
                dumped_stage["storyBlockId"] = _authority_id(
                    identities, "story-block", stage.story_block_id
                )
            for task, dumped_task in zip(stage.scene_tasks, dumped_stage["sceneTasks"], strict=True):
                replace_definition(task, dumped_task, "scene-task")
                if isinstance(planning, PlanningAggregate):
                    dumped_task["stageId"] = _authority_id(identities, "planning-stage", task.stage_id)
    if isinstance(planning, PlanningAggregate):
        if planning.active_story_block_id is not None:
            payload["activeStoryBlockId"] = _authority_id(
                identities, "story-block", planning.active_story_block_id
            )
    elif planning.active_story_block_ref is not None:
        payload["activeStoryBlockRef"] = _authority_id(
            identities, "story-block", planning.active_story_block_ref
        )
    return payload


def _register_bible_items(
    bible: BiblePayload,
    identities: dict[tuple[str, object], str],
    counters: dict[str, int],
) -> None:
    for field_name, kind in _BIBLE_ITEM_TYPES.items():
        for item in getattr(bible, field_name):
            _register_authority_id(identities, counters, kind, item.id)


def _rewrite_bible_payload(
    bible: BiblePayload,
    identities: Mapping[tuple[str, object], str],
) -> dict[str, object]:
    payload = bible.model_dump(mode="json", by_alias=True)
    for field_name, kind in _BIBLE_ITEM_TYPES.items():
        for item, dumped in zip(getattr(bible, field_name), payload[field_name], strict=True):
            dumped["id"] = _authority_id(identities, kind, item.id)
    return payload


def _validate_outline_payload(
    table: str, value: object,
) -> ChapterOutline | DraftChapterOutline | EditableChapterOutlineContent:
    parsed = _json_value(value)
    if table == "chapter_outline_revisions":
        return ChapterOutline.model_validate(parsed)
    for model in (ChapterOutline, DraftChapterOutline, EditableChapterOutlineContent):
        try:
            return model.model_validate(parsed)
        except ValueError:
            pass
    raise _invalid()


def _rewrite_outline_payload(
    outline: ChapterOutline | DraftChapterOutline | EditableChapterOutlineContent,
    planning_identities: Mapping[tuple[str, object], str],
    planning_revision_ids: Mapping[object, str],
) -> dict[str, object]:
    payload = outline.model_dump(mode="json", by_alias=True)
    if isinstance(outline, (ChapterOutline, DraftChapterOutline)):
        planning_logical_id = planning_revision_ids.get(outline.planning_revision_id)
        if planning_logical_id is None:
            raise _invalid()
        payload["planningRevisionId"] = planning_logical_id
    references = (
        ("volumeRef", "planning-volume", (outline.volume_ref,) if outline.volume_ref is not None else ()),
        ("storyBlockRef", "story-block", (outline.story_block_ref,) if outline.story_block_ref is not None else ()),
        ("stageRefs", "planning-stage", outline.stage_refs),
        ("sceneTaskRefs", "scene-task", outline.scene_task_refs),
    )
    for field_name, kind, values in references:
        if field_name in {"volumeRef", "storyBlockRef"}:
            if values:
                payload[field_name]["id"] = _authority_id(planning_identities, kind, values[0].id)
        else:
            for value, dumped in zip(values, payload[field_name], strict=True):
                dumped["id"] = _authority_id(planning_identities, kind, value.id)
    return payload


def _rewrite_creation_contract_payload(
    contract: CreationContractPayload,
    *,
    seed_revision_ids: Mapping[tuple[object, object], str],
    engine_option_ids: Mapping[tuple[object, object], str],
    binding_revision_ids: Mapping[tuple[object, object, object], str],
    frozen_asset_ids: Mapping[tuple[object, object, object], str],
    corpus_revision_ids: Mapping[tuple[object, object, object], str],
    corpus_revision_database_ids: Mapping[object, str],
    corpus_chapter_ids: Mapping[tuple[str, object], str],
    corpus_fragment_ids: Mapping[
        tuple[str, object, object, object], tuple[str, object, object]
    ],
) -> dict[str, object]:
    payload = contract.model_dump(mode="json", by_alias=True)

    seed_logical_id = seed_revision_ids.get((contract.seedRevisionId, contract.seedHash))
    engine_logical_id = engine_option_ids.get((contract.engineOptionId, contract.engineHash))
    if seed_logical_id is None or engine_logical_id is None:
        raise _invalid()
    payload["seedRevisionId"] = seed_logical_id
    payload["engineOptionId"] = engine_logical_id

    def rewrite_asset_ref(ref, dumped: dict[str, object]) -> None:
        logical_id = frozen_asset_ids.get((ref.id, ref.revision, ref.contentHash))
        if logical_id is None:
            raise _invalid()
        dumped["id"] = logical_id

    rewrite_asset_ref(contract.primaryStyleRef, payload["primaryStyleRef"])
    if contract.secondaryStyleRef is not None:
        rewrite_asset_ref(contract.secondaryStyleRef, payload["secondaryStyleRef"])
    for ref, dumped in zip(
        contract.experienceCardRefs, payload["experienceCardRefs"], strict=True,
    ):
        rewrite_asset_ref(ref, dumped)

    for source, dumped_source in zip(
        contract.corpusSourceRefs, payload["corpusSourceRefs"], strict=True,
    ):
        reference = (source.id, source.revision, source.contentHash)
        revision_logical_id = corpus_revision_ids.get(reference)
        if (
            revision_logical_id is None
            or corpus_revision_database_ids.get(source.revisionId) != revision_logical_id
        ):
            raise _invalid()
        dumped_source["id"] = revision_logical_id
        dumped_source["revisionId"] = revision_logical_id
        for fragment, dumped_fragment in zip(
            source.fragments, dumped_source["fragments"], strict=True,
        ):
            chapter_logical_id = corpus_chapter_ids.get((
                revision_logical_id, fragment.chapterId,
            ))
            fragment_target = corpus_fragment_ids.get((
                revision_logical_id,
                fragment.chapterId,
                fragment.fragmentId,
                fragment.fragmentHash,
            ))
            if fragment_target is None:
                raise _invalid()
            fragment_logical_id, fragment_start, fragment_end = fragment_target
            if (
                chapter_logical_id is None
                or not fragment_start <= fragment.chapterCharStart
                or not fragment.chapterCharEnd <= fragment_end
            ):
                raise _invalid()
            dumped_fragment["chapterId"] = chapter_logical_id
            dumped_fragment["fragmentId"] = fragment_logical_id

    if contract.modelBindingRef is not None:
        binding_logical_id = binding_revision_ids.get((
            contract.modelBindingRef.id,
            contract.modelBindingRef.revision,
            contract.modelBindingRef.contentHash,
        ))
        if binding_logical_id is None:
            raise _invalid()
        payload["modelBindingRef"]["id"] = binding_logical_id
    return payload


_FINALIZATION_PLANNING_TARGET_KINDS: Mapping[str, str] = MappingProxyType({
    "volume": "planning-volume",
    "plot": "planning-plot",
    "story_block": "story-block",
    "stage": "planning-stage",
    "scene_task": "scene-task",
})


def _next_authority_logical_id(counters: dict[str, int], kind: str) -> str:
    counters[kind] = counters.get(kind, 0) + 1
    return f"{kind}:{counters[kind]}"


def _rewrite_finalization_change_set(
    change_set: FinalizationChangeSet,
    *,
    planning_identities: Mapping[tuple[str, object], str],
    canon_entity_ids: Mapping[object, str],
    counters: dict[str, int],
) -> dict[str, object]:
    payload = change_set_payload(change_set)
    local_id_fields = (
        (change_set.entities, payload["entities"], "finalization-entity"),
        (change_set.aliases, payload["aliases"], "finalization-alias"),
        (change_set.canon_events, payload["canonEvents"], "finalization-event"),
        (
            change_set.story_progress_events,
            payload["storyProgressEvents"],
            "finalization-progress-event",
        ),
        (
            change_set.planning_patches,
            payload["planningPatches"],
            "finalization-planning-patch",
        ),
        (
            change_set.planning_suggestions,
            payload["planningSuggestions"],
            "finalization-planning-suggestion",
        ),
    )
    local_ids: dict[object, str] = {}
    for values, dumped_values, kind in local_id_fields:
        for value, dumped in zip(values, dumped_values, strict=True):
            if value.id in local_ids:
                raise _invalid()
            logical_id = _next_authority_logical_id(counters, kind)
            local_ids[value.id] = logical_id
            dumped["id"] = logical_id

    existing_entity_ids: dict[object, str] = {}
    for raw_id in change_set.existing_entity_ids:
        logical_id = canon_entity_ids.get(raw_id)
        if logical_id is None or raw_id in existing_entity_ids:
            raise _invalid()
        existing_entity_ids[raw_id] = logical_id
    payload["existingEntityIds"] = [
        existing_entity_ids[raw_id] for raw_id in change_set.existing_entity_ids
    ]
    new_entity_ids = {
        entity.id: local_ids[entity.id] for entity in change_set.entities
    }

    def entity_reference(raw_id: object) -> str:
        logical_id = new_entity_ids.get(raw_id, existing_entity_ids.get(raw_id))
        if logical_id is None:
            raise _invalid()
        return logical_id

    for value, dumped in zip(change_set.aliases, payload["aliases"], strict=True):
        dumped["entityId"] = entity_reference(value.entity_id)
    for value, dumped in zip(change_set.canon_events, payload["canonEvents"], strict=True):
        if value.entity_id is not None:
            dumped["entityId"] = entity_reference(value.entity_id)

    def planning_reference(target_type: object, raw_id: object) -> str:
        kind = _FINALIZATION_PLANNING_TARGET_KINDS.get(str(target_type))
        if kind is None:
            raise _invalid()
        return _authority_id(planning_identities, kind, raw_id)

    for value, dumped in zip(
        change_set.story_progress_events, payload["storyProgressEvents"], strict=True,
    ):
        dumped["targetId"] = planning_reference(value.target_type.value, value.target_id)
    for value, dumped in zip(
        change_set.planning_patches, payload["planningPatches"], strict=True,
    ):
        dumped["targetId"] = planning_reference(value.target_type.value, value.target_id)
    for value, dumped in zip(
        change_set.planning_suggestions, payload["planningSuggestions"], strict=True,
    ):
        if value.target_id is None:
            continue
        matches = [
            planning_identities[(kind, value.target_id)]
            for kind in _FINALIZATION_PLANNING_TARGET_KINDS.values()
            if (kind, value.target_id) in planning_identities
        ]
        if len(matches) != 1:
            raise _invalid()
        dumped["targetId"] = matches[0]
    return payload


def _rewrite_quality_findings(
    value: object,
    *,
    counters: dict[str, int],
) -> list[dict[str, object]]:
    parsed = _json_value(value)
    if not isinstance(parsed, list) or len(parsed) > 256:
        raise _invalid()
    findings = [QualityFinding.model_validate(item) for item in parsed]
    raw_ids: set[str] = set()
    payload: list[dict[str, object]] = []
    for finding in findings:
        if finding.id in raw_ids:
            raise _invalid()
        raw_ids.add(finding.id)
        dumped = finding.model_dump(mode="json", by_alias=True)
        dumped["id"] = _next_authority_logical_id(counters, "quality-finding")
        payload.append(dumped)
    return payload


def _rewrite_finalization_receipt(
    value: object,
    record: Mapping[str, object],
    *,
    final_chapter_rows: Mapping[object, Mapping[str, object]],
    planning_revision_rows: Mapping[object, Mapping[str, object]],
    final_chapter_ids: Mapping[object, str],
    planning_revision_ids: Mapping[object, str],
) -> dict[str, object]:
    receipt = _json_value(value)
    expected_fields = {
        "finalChapterId", "canonRevision", "projectionHash",
        "planningRevisionId", "planningRevision", "planningHash",
    }
    if not isinstance(receipt, Mapping) or set(receipt) != expected_fields:
        raise _invalid()
    final_chapter_id = receipt["finalChapterId"]
    planning_revision_id = receipt["planningRevisionId"]
    if (
        not isinstance(final_chapter_id, str)
        or not final_chapter_id
        or not isinstance(planning_revision_id, str)
        or not planning_revision_id
        or type(receipt["canonRevision"]) is not int
        or receipt["canonRevision"] < 1
        or type(receipt["planningRevision"]) is not int
        or receipt["planningRevision"] < 1
        or not isinstance(receipt["projectionHash"], str)
        or re.fullmatch(r"[0-9a-f]{64}", receipt["projectionHash"]) is None
        or not isinstance(receipt["planningHash"], str)
        or re.fullmatch(r"[0-9a-f]{64}", receipt["planningHash"]) is None
    ):
        raise _invalid()

    final_chapter = final_chapter_rows.get(final_chapter_id)
    planning_revision = planning_revision_rows.get(planning_revision_id)
    final_chapter_logical_id = final_chapter_ids.get(final_chapter_id)
    planning_revision_logical_id = planning_revision_ids.get(planning_revision_id)
    if (
        final_chapter is None
        or planning_revision is None
        or final_chapter_logical_id is None
        or planning_revision_logical_id is None
        or final_chapter["finalization_record_id"] != record["id"]
        or final_chapter["planning_revision_id"] != planning_revision_id
        or final_chapter["planning_revision"] != receipt["planningRevision"]
        or final_chapter["planning_hash"] != receipt["planningHash"]
        or final_chapter["canon_revision"] != receipt["canonRevision"]
        or planning_revision["revision"] != receipt["planningRevision"]
        or planning_revision["content_hash"] != receipt["planningHash"]
        or record["committed_canon_revision"] != receipt["canonRevision"]
    ):
        raise _invalid()
    return dict(receipt) | {
        "finalChapterId": final_chapter_logical_id,
        "planningRevisionId": planning_revision_logical_id,
    }


def _invalid() -> ProjectPackageInvalid:
    return ProjectPackageInvalid("invalid package value")


@dataclass(frozen=True, slots=True)
class FrozenCorpusBlob:
    logical_id: str
    content_hash: str
    byte_length: int
    storage_key: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.logical_id, str)
            or not re.fullmatch(r"corpus-blob:[1-9][0-9]*", self.logical_id)
            or not isinstance(self.content_hash, str)
            or not re.fullmatch(r"[0-9a-f]{64}", self.content_hash)
            or type(self.byte_length) is not int
            or self.byte_length < 0
            or not isinstance(self.storage_key, str)
        ):
            raise _invalid()
        try:
            expected_storage_key = managed_corpus_storage_key(self.content_hash)
        except UnsafeLocalPath:
            raise _invalid() from None
        if self.storage_key != expected_storage_key:
            raise _invalid()


@dataclass(frozen=True, slots=True)
class ProjectPackageSnapshot:
    source_project_logical_id: str
    lifecycle_revision: int
    graph_records: tuple[PackageRecord, ...]
    operation_records: tuple[PackageRecord, ...]
    provider_history_records: tuple[PackageRecord, ...]
    frozen_asset_records: tuple[PackageRecord, ...]
    corpus_revision_records: tuple[PackageRecord, ...]
    corpus_blobs: tuple[FrozenCorpusBlob, ...]
    projection_validation: Mapping[str, object]
    referenced_secret_values: tuple[bytes, ...] = field(repr=False)
    counts: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        record_groups = (
            self.graph_records,
            self.operation_records,
            self.provider_history_records,
            self.frozen_asset_records,
            self.corpus_revision_records,
        )
        if (
            not isinstance(self.source_project_logical_id, str)
            or not re.fullmatch(r"project:[1-9][0-9]*", self.source_project_logical_id)
            or type(self.lifecycle_revision) is not int
            or self.lifecycle_revision < 0
            or any(type(group) is not tuple for group in record_groups)
            or type(self.corpus_blobs) is not tuple
            or type(self.referenced_secret_values) is not tuple
            or any(type(record) is not PackageRecord for group in record_groups for record in group)
            or any(type(blob) is not FrozenCorpusBlob for blob in self.corpus_blobs)
            or not isinstance(self.projection_validation, Mapping)
            or any(type(value) is not bytes for value in self.referenced_secret_values)
            or not isinstance(self.counts, Mapping)
            or any(not isinstance(key, str) or type(value) is not int or value < 0 for key, value in self.counts.items())
        ):
            raise _invalid()
        object.__setattr__(self, "projection_validation", freeze_json_value(self.projection_validation))
        object.__setattr__(self, "counts", MappingProxyType(dict(self.counts)))


class ProjectPackageRepository:
    """Materialize one deterministic package graph from a single database snapshot."""

    def __init__(self, *, pool, session_factory=DatabaseSession) -> None:
        self._pool = pool
        self._session_factory = session_factory

    async def read_snapshot(self, project_id: str, expected_lifecycle_revision: int) -> ProjectPackageSnapshot:
        raw = await self._pool.acquire()
        session = self._session_factory(raw)
        try:
            await session.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            await session.execute("START TRANSACTION READ ONLY, WITH CONSISTENT SNAPSHOT")
            project = await session.fetchone(
                "SELECT id,lifecycle_revision FROM projects WHERE id=%s", (project_id,)
            )
            if project is None:
                raise ProjectPackageNotFound("project package not found")
            if project["lifecycle_revision"] != expected_lifecycle_revision:
                raise ProjectPackageConflict("project package conflict")
            busy = await session.fetchone(
                """SELECT 1 AS present WHERE EXISTS (SELECT 1 FROM draft_operation_attempts WHERE project_id=%s AND active_slot=1 AND status IN ('starting','running')) OR EXISTS (SELECT 1 FROM market_analyses WHERE project_id=%s AND status IN ('reserved','running')) OR EXISTS (SELECT 1 FROM finalization_change_sets WHERE project_id=%s AND status IN ('preparing','awaiting_author','committing'))""",
                (project_id, project_id, project_id),
            )
            if busy is not None:
                raise ProjectPackageBusy("project package busy")

            rows_by_table: dict[str, tuple[Mapping[str, object], ...]] = {}
            for table, plan in PROJECT_OWNED_QUERY_PLANS.items():
                rows = tuple(await session.fetchall(plan.sql, (project_id,)))
                if any(not isinstance(row, Mapping) or set(row) != set(plan.selected_columns) for row in rows):
                    raise _invalid()
                rows_by_table[table] = rows

            provenance_columns = (
                "record_order", "category", "source_entity_type",
                "source_logical_id", "payload_json", "content_hash", "created_at",
            )
            provenance_rows = tuple(await session.fetchall(
                """SELECT record_order,category,source_entity_type,
                          source_logical_id,payload_json,content_hash,created_at
                   FROM project_import_provenance
                   WHERE project_id=%s ORDER BY record_order""",
                (project_id,),
            ))
            if any(
                not isinstance(row, Mapping) or set(row) != set(provenance_columns)
                for row in provenance_rows
            ):
                raise _invalid()

            market_evidence_by_analysis: dict[object, Mapping[str, object]] = {}
            for analysis_id, snapshot_id, snapshot_hash in sorted({
                (row["market_analysis_id"], row["market_snapshot_id"], row["market_snapshot_hash"])
                for row in rows_by_table["seed_inspiration_attempts"]
                if row["market_analysis_id"] is not None
            }):
                matched = tuple(await session.fetchall(
                    _MARKET_SNAPSHOT_EVIDENCE_QUERY, (snapshot_id, snapshot_hash)
                ))
                if len(matched) != 1 or set(matched[0]) != {"snapshot_hash", "captured_at"}:
                    raise _invalid()
                existing = market_evidence_by_analysis.get(analysis_id)
                if existing is not None and existing != matched[0]:
                    raise _invalid()
                market_evidence_by_analysis[analysis_id] = matched[0]

            frozen_asset_rows: dict[str, tuple[Mapping[str, object], ...]] = {}
            frozen_asset_refs = {
                "experience_cards": sorted({
                    (row["experience_card_id"], row["asset_revision"], row["asset_hash"])
                    for row in rows_by_table["creation_contract_experience_refs"]
                }),
                "style_templates": sorted({
                    (row["style_template_id"], row["asset_revision"], row["asset_hash"])
                    for row in rows_by_table["style_contract_template_refs"]
                }),
            }
            for table in sorted(_FROZEN_ASSET_QUERIES):
                materialized: list[Mapping[str, object]] = []
                for reference in frozen_asset_refs[table]:
                    matched = tuple(await session.fetchall(_FROZEN_ASSET_QUERIES[table], reference))
                    if len(matched) != 1:
                        raise _invalid()
                    materialized.append(matched[0])
                frozen_asset_rows[table] = tuple(materialized)

            corpus_revision_ref_set = {
                (row["corpus_source_id"], row["source_revision"], row["source_hash"])
                for table in ("creation_contract_corpus_refs", "creation_contract_corpus_fragment_refs")
                for row in rows_by_table[table]
            }
            for source_id, chapter_id in sorted({
                (row["corpus_source_id"], row["corpus_chapter_id"])
                for row in rows_by_table["reference_uses"]
            }):
                matched = tuple(await session.fetchall(
                    _REFERENCE_USE_CORPUS_REVISION_QUERY, (source_id, chapter_id)
                ))
                if len(matched) != 1 or set(matched[0]) != {"source_id", "revision", "content_hash"}:
                    raise _invalid()
                corpus_revision_ref_set.add((
                    matched[0]["source_id"], matched[0]["revision"], matched[0]["content_hash"]
                ))
            corpus_revision_refs = sorted(corpus_revision_ref_set)
            frozen_corpus_rows: list[Mapping[str, object]] = []
            frozen_corpus_descriptors: dict[object, tuple[tuple[Mapping[str, object], tuple[Mapping[str, object], ...]], ...]] = {}
            for reference in corpus_revision_refs:
                matched = tuple(await session.fetchall(_FROZEN_CORPUS_REVISION_QUERY, reference))
                if len(matched) != 1:
                    raise _invalid()
                revision_row = matched[0]
                frozen_corpus_rows.append(revision_row)
                chapters = tuple(await session.fetchall(
                    _FROZEN_CORPUS_CHAPTER_QUERY, (revision_row["source_id"], revision_row["id"])
                ))
                chapter_descriptors: list[tuple[Mapping[str, object], tuple[Mapping[str, object], ...]]] = []
                for chapter in chapters:
                    fragments = tuple(await session.fetchall(
                        _FROZEN_CORPUS_FRAGMENT_QUERY, (revision_row["source_id"], chapter["chapter_id"])
                    ))
                    chapter_descriptors.append((chapter, fragments))
                frozen_corpus_descriptors[revision_row["id"]] = tuple(chapter_descriptors)

            provider_rows = tuple(await session.fetchall(_PROVIDER_PROFILE_QUERY, (project_id,)))
            projection_rows = {
                name: tuple(await session.fetchall(sql, (project_id,)))
                for name, sql in _PROJECTION_QUERIES.items()
            }

            try:
                identity_maps: dict[str, dict[object, str]] = {
                    table: {} for table in PROJECT_OWNED_TABLES | set(NORMALIZED_SHARED_RECORD_TYPES)
                }
                logical_ids_by_table: dict[str, tuple[str, ...]] = {}
                counters: dict[str, int] = {}
                for table in sorted(PROJECT_OWNED_TABLES):
                    record_type = PROJECT_TABLE_RECORD_TYPES[table]
                    logical_ids: list[str] = []
                    for row in rows_by_table[table]:
                        counters[record_type] = counters.get(record_type, 0) + 1
                        logical_id = f"{record_type}:{counters[record_type]}"
                        logical_ids.append(logical_id)
                        database_id = row.get("id")
                        if database_id is not None:
                            if database_id in identity_maps[table]:
                                raise _invalid()
                            identity_maps[table][database_id] = logical_id
                    logical_ids_by_table[table] = tuple(logical_ids)

                authority_identities: dict[tuple[str, object], str] = {}
                authority_counters: dict[str, int] = {}
                planning_models: dict[int, PlanningAggregate | DraftPlanningAggregate] = {}
                for table in ("planning_revisions", "planning_drafts"):
                    for row in rows_by_table[table]:
                        planning = _validate_planning_payload(table, row["content_json"])
                        planning_models[id(row)] = planning
                        _register_planning_nodes(planning, authority_identities, authority_counters)

                bible_models: dict[int, BiblePayload] = {}
                for table, column in (
                    ("creation_bible_revisions", "content_json"),
                    ("project_bible_drafts", "draft_json"),
                ):
                    for row in rows_by_table[table]:
                        bible = BiblePayload.model_validate_json(
                            json.dumps(_json_value(row[column]), ensure_ascii=False)
                        )
                        bible_models[id(row)] = bible
                        _register_bible_items(bible, authority_identities, authority_counters)

                planning_revision_ids: dict[object, str] = {}
                for table in ("planning_revisions", "planning_drafts"):
                    for database_id, logical_id in identity_maps[table].items():
                        existing = planning_revision_ids.get(database_id)
                        if existing is not None and existing != logical_id:
                            raise _invalid()
                        planning_revision_ids[database_id] = logical_id

                outline_models: dict[
                    int, ChapterOutline | DraftChapterOutline | EditableChapterOutlineContent
                ] = {}
                for table in ("chapter_outline_revisions", "chapter_outline_drafts"):
                    for row in rows_by_table[table]:
                        outline_models[id(row)] = _validate_outline_payload(table, row["content_json"])

                creation_contract_models: dict[int, CreationContractPayload] = {}
                for row in rows_by_table["creation_contracts"]:
                    creation_contract_models[id(row)] = CreationContractPayload.model_validate_json(
                        json.dumps(_json_value(row["content_json"]), ensure_ascii=False)
                    )

                finalization_change_set_models: dict[int, FinalizationChangeSet] = {}
                for row in rows_by_table["finalization_change_set_revisions"]:
                    finalization_change_set_models[id(row)] = FinalizationChangeSet.model_validate(
                        _json_value(row["payload_json"])
                    )

                quality_findings_payloads = {
                    id(row): _rewrite_quality_findings(
                        row["findings_json"], counters=authority_counters,
                    )
                    for row in rows_by_table["candidate_quality_reports"]
                }

                authority_payloads: dict[int, object] = {
                    row_id: _rewrite_planning_payload(model, authority_identities)
                    for row_id, model in planning_models.items()
                }
                authority_payloads.update({
                    row_id: _rewrite_bible_payload(model, authority_identities)
                    for row_id, model in bible_models.items()
                })
                authority_payloads.update({
                    row_id: _rewrite_outline_payload(
                        model, authority_identities, planning_revision_ids
                    )
                    for row_id, model in outline_models.items()
                })
                authority_payloads.update({
                    row_id: _rewrite_finalization_change_set(
                        model,
                        planning_identities=authority_identities,
                        canon_entity_ids=identity_maps["canon_entities"],
                        counters=authority_counters,
                    )
                    for row_id, model in finalization_change_set_models.items()
                })
                final_chapter_rows_by_id = {
                    row["id"]: row for row in rows_by_table["final_chapters"]
                }
                planning_revision_rows_by_id = {
                    row["id"]: row for row in rows_by_table["planning_revisions"]
                }
                authority_payloads.update({
                    id(row): _rewrite_finalization_receipt(
                        row["result_payload_json"],
                        row,
                        final_chapter_rows=final_chapter_rows_by_id,
                        planning_revision_rows=planning_revision_rows_by_id,
                        final_chapter_ids=identity_maps["final_chapters"],
                        planning_revision_ids=identity_maps["planning_revisions"],
                    )
                    for row in rows_by_table["finalization_records"]
                })
                nested_story_blocks = {
                    raw_id: logical_id
                    for (kind, raw_id), logical_id in authority_identities.items()
                    if kind == "story-block"
                }

                frozen_asset_records: list[PackageRecord] = []
                shared_assets_by_id: dict[str, Mapping[str, object]] = {}
                for table in sorted(frozen_asset_rows):
                    for row in frozen_asset_rows[table]:
                        expected_columns = {
                            "id", "stable_key", "revision", "payload_json", "provenance_json",
                            "content_hash", "status", "created_at",
                        } | ({"name"} if table == "style_templates" else {"title", "category"})
                        if not isinstance(row, Mapping) or set(row) != expected_columns:
                            raise _invalid()
                        database_id = row["id"]
                        if database_id in identity_maps[table]:
                            raise _invalid()
                        counters["asset"] = counters.get("asset", 0) + 1
                        logical_id = f"asset:{counters['asset']}"
                        identity_maps[table][database_id] = logical_id
                        shared_assets_by_id[database_id] = row
                        data = {
                            "assetKind": "style-template" if table == "style_templates" else "experience-card",
                            "stableKey": row["stable_key"],
                            "revision": row["revision"],
                            "name": row.get("name", row.get("title")),
                            "payload": _json_value(row["payload_json"]),
                            "provenance": _json_value(row["provenance_json"]),
                            "contentHash": row["content_hash"],
                            "status": row["status"],
                            "createdAt": row["created_at"],
                        }
                        if row.get("category") is not None:
                            data["category"] = row["category"]
                        frozen_asset_records.append(PackageRecord(
                            "asset", logical_id, revision=row["revision"], data=data,
                        ))

                corpus_revision_records: list[PackageRecord] = []
                corpus_blobs: list[FrozenCorpusBlob] = []
                corpus_logical_ids_by_ref: dict[tuple[object, object, object], str] = {}
                corpus_reference_by_chapter: dict[tuple[object, object], tuple[object, object, object]] = {}
                corpus_chapter_logical_ids: dict[tuple[str, object], str] = {}
                corpus_fragment_logical_ids: dict[
                    tuple[str, object, object, object], tuple[str, object, object]
                ] = {}
                blob_logical_ids_by_hash: dict[str, str] = {}
                expected_corpus_columns = {
                    "id", "source_id", "source_key", "revision", "content_hash", "relative_path",
                    "display_name", "author", "reference_tags_json", "notes", "provenance_json",
                    "byte_length", "encoding", "parser_version", "normalizer_version",
                    "fragmenter_version", "index_version", "status", "imported_at", "analyzed_at",
                    "created_at", "blob_byte_length", "storage_key",
                }
                expected_chapter_columns = {
                    "chapter_id", "chapter_order", "title", "raw_byte_start", "raw_byte_end",
                    "normalized_char_start", "normalized_char_end", "normalized_text", "content_hash",
                    "created_at",
                }
                expected_fragment_columns = {
                    "fragment_id", "fragment_order", "chapter_char_start", "chapter_char_end",
                    "normalized_text", "content_hash", "analysis_version", "index_payload", "created_at",
                }
                corpus_chapter_count = 0
                corpus_fragment_count = 0
                for row in frozen_corpus_rows:
                    if not isinstance(row, Mapping) or set(row) != expected_corpus_columns:
                        raise _invalid()
                    reference = (row["source_id"], row["revision"], row["content_hash"])
                    if reference in corpus_logical_ids_by_ref:
                        raise _invalid()
                    counters["corpus-revision"] = counters.get("corpus-revision", 0) + 1
                    logical_id = f"corpus-revision:{counters['corpus-revision']}"
                    corpus_logical_ids_by_ref[reference] = logical_id
                    identity_maps["corpus_source_revisions"][row["id"]] = logical_id
                    chapters_data: list[dict[str, object]] = []
                    fragments_data: list[dict[str, object]] = []
                    for chapter, fragments in frozen_corpus_descriptors[row["id"]]:
                        if not isinstance(chapter, Mapping) or set(chapter) != expected_chapter_columns:
                            raise _invalid()
                        chapter_order = chapter["chapter_order"]
                        chapter_reference_key = (row["source_id"], chapter["chapter_id"])
                        if chapter_reference_key in corpus_reference_by_chapter:
                            raise _invalid()
                        corpus_reference_by_chapter[chapter_reference_key] = reference
                        corpus_chapter_count += 1
                        chapter_logical_id = f"corpus-chapter:{corpus_chapter_count}"
                        if (logical_id, chapter["chapter_id"]) in corpus_chapter_logical_ids:
                            raise _invalid()
                        corpus_chapter_logical_ids[(
                            logical_id, chapter["chapter_id"],
                        )] = chapter_logical_id
                        chapters_data.append({
                            "logicalId": chapter_logical_id,
                            "chapterOrder": chapter_order, "title": chapter["title"],
                            "rawByteStart": chapter["raw_byte_start"], "rawByteEnd": chapter["raw_byte_end"],
                            "normalizedCharStart": chapter["normalized_char_start"],
                            "normalizedCharEnd": chapter["normalized_char_end"],
                            "normalizedText": chapter["normalized_text"],
                            "contentHash": chapter["content_hash"], "createdAt": chapter["created_at"],
                        })
                        for fragment in fragments:
                            if not isinstance(fragment, Mapping) or set(fragment) != expected_fragment_columns:
                                raise _invalid()
                            corpus_fragment_count += 1
                            fragment_logical_id = f"corpus-fragment:{corpus_fragment_count}"
                            fragment_reference = (
                                logical_id,
                                chapter["chapter_id"],
                                fragment["fragment_id"],
                                fragment["content_hash"],
                            )
                            if fragment_reference in corpus_fragment_logical_ids:
                                raise _invalid()
                            corpus_fragment_logical_ids[fragment_reference] = (
                                fragment_logical_id,
                                fragment["chapter_char_start"],
                                fragment["chapter_char_end"],
                            )
                            fragments_data.append({
                                "logicalId": fragment_logical_id,
                                "chapterOrder": chapter_order, "fragmentOrder": fragment["fragment_order"],
                                "chapterCharStart": fragment["chapter_char_start"],
                                "chapterCharEnd": fragment["chapter_char_end"],
                                "normalizedText": fragment["normalized_text"],
                                "contentHash": fragment["content_hash"], "createdAt": fragment["created_at"],
                                "analysisVersion": fragment["analysis_version"],
                                "indexPayload": _json_value(fragment["index_payload"]),
                            })
                    corpus_revision_records.append(PackageRecord(
                        "corpus-revision",
                        logical_id,
                        revision=row["revision"],
                        data={
                            "sourceKey": row["source_key"], "revision": row["revision"],
                            "relativePath": row["relative_path"], "displayName": row["display_name"],
                            "author": row["author"], "referenceTags": _json_value(row["reference_tags_json"]),
                            "notes": row["notes"], "provenance": _json_value(row["provenance_json"]),
                            "contentHash": row["content_hash"], "byteLength": row["byte_length"],
                            "encoding": row["encoding"], "parserVersion": row["parser_version"],
                            "normalizerVersion": row["normalizer_version"],
                            "fragmenterVersion": row["fragmenter_version"], "indexVersion": row["index_version"],
                            "status": row["status"], "importedAt": row["imported_at"],
                            "analyzedAt": row["analyzed_at"], "createdAt": row["created_at"],
                            "chapters": tuple(chapters_data), "fragments": tuple(fragments_data),
                        },
                    ))
                    content_hash = row["content_hash"]
                    if content_hash not in blob_logical_ids_by_hash:
                        blob_logical_id = f"corpus-blob:{len(blob_logical_ids_by_hash) + 1}"
                        blob_logical_ids_by_hash[content_hash] = blob_logical_id
                        corpus_blobs.append(FrozenCorpusBlob(
                            blob_logical_id, content_hash, row["blob_byte_length"], row["storage_key"]
                        ))

                seed_revision_ids = {
                    (row["id"], row["content_hash"]): identity_maps["creative_seed_revisions"][row["id"]]
                    for row in rows_by_table["creative_seed_revisions"]
                }
                engine_option_ids = {
                    (row["id"], row["content_hash"]): identity_maps["story_engine_options"][row["id"]]
                    for row in rows_by_table["story_engine_options"]
                }
                binding_revision_ids = {
                    (row["id"], row["revision"], row["content_hash"]):
                        identity_maps["project_model_binding_revisions"][row["id"]]
                    for row in rows_by_table["project_model_binding_revisions"]
                }
                frozen_asset_ids = {
                    (row["id"], row["revision"], row["content_hash"]):
                        identity_maps[table][row["id"]]
                    for table, rows in frozen_asset_rows.items()
                    for row in rows
                }
                authority_payloads.update({
                    id(row): _rewrite_creation_contract_payload(
                        creation_contract_models[id(row)],
                        seed_revision_ids=seed_revision_ids,
                        engine_option_ids=engine_option_ids,
                        binding_revision_ids=binding_revision_ids,
                        frozen_asset_ids=frozen_asset_ids,
                        corpus_revision_ids=corpus_logical_ids_by_ref,
                        corpus_revision_database_ids=identity_maps["corpus_source_revisions"],
                        corpus_chapter_ids=corpus_chapter_logical_ids,
                        corpus_fragment_ids=corpus_fragment_logical_ids,
                    )
                    for row in rows_by_table["creation_contracts"]
                })

                graph_records: list[PackageRecord] = []
                operation_records: list[PackageRecord] = []
                provider_history_records: list[PackageRecord] = []
                counts: dict[str, int] = {}
                for row in sorted(provenance_rows, key=lambda item: item["record_order"]):
                    record_order = row["record_order"]
                    if type(record_order) is not int or record_order <= 0:
                        raise _invalid()
                    operation_records.append(PackageRecord(
                        "import-provenance",
                        f"import-provenance:{record_order}",
                        order=record_order,
                        data={
                            "category": row["category"],
                            "sourceEntityType": row["source_entity_type"],
                            "sourceLogicalId": row["source_logical_id"],
                            "payload": _json_value(row["payload_json"]),
                            "contentHash": row["content_hash"],
                            "createdAt": row["created_at"],
                        },
                    ))
                    counts["import-provenance"] = counts.get("import-provenance", 0) + 1
                for table in sorted(PROJECT_OWNED_TABLES):
                    record_type = PROJECT_TABLE_RECORD_TYPES[table]
                    allowlist = RECORD_FIELD_ALLOWLISTS[record_type]
                    for row, logical_id in zip(rows_by_table[table], logical_ids_by_table[table], strict=True):
                        if table in {
                            "contract_confirmation_requests", "bible_confirmation_requests",
                            "planning_confirmation_requests", "chapter_outline_confirmation_requests",
                        } and row["status"] not in {"succeeded"}:
                            payload = {
                                "status": row["status"],
                                "createdAt": row["created_at"],
                                "completedAt": row["completed_at"],
                            }
                            record_order = max((item.order for item in operation_records), default=0) + 1
                            operation_records.append(PackageRecord(
                                "import-provenance", f"import-provenance:{record_order}",
                                order=record_order, data={
                                    "category": "unsupported-history",
                                    "sourceEntityType": record_type,
                                    "sourceLogicalId": logical_id,
                                    "payload": payload,
                                    "contentHash": sha256(json.dumps(
                                        payload, sort_keys=True, separators=(",", ":"),
                                    ).encode("utf-8")).hexdigest(),
                                    "createdAt": row["created_at"],
                                },
                            ))
                            counts["import-provenance"] = counts.get("import-provenance", 0) + 1
                            continue
                        data: dict[str, object] = {}
                        for column, category in PROJECT_TABLE_COLUMN_POLICIES[table].items():
                            if category in {"derived", "excluded_sensitive_operational"}:
                                continue
                            value = row[column]
                            if table == "project_model_binding_revisions" and column == "source_project_id":
                                if value == project_id:
                                    data["sourceProjectLogicalId"] = identity_maps["projects"][project_id]
                                elif value is not None:
                                    data["sourceKind"] = "inherited"
                                continue
                            if category in {"public_field", "normalized_inert_evidence"}:
                                field_name = PACKAGE_COLUMN_EXPORT_DECISIONS[(table, column)]
                                if field_name.startswith("@"):
                                    continue
                                if column.endswith("_json") and value is not None:
                                    if table == "candidate_quality_reports" and column == "findings_json":
                                        value = quality_findings_payloads[id(row)]
                                    else:
                                        value = (
                                            authority_payloads[id(row)]
                                            if id(row) in authority_payloads
                                            else _json_value(value)
                                        )
                                data[field_name] = value
                                continue
                            if category == "logical_reference":
                                if value is None:
                                    continue
                                target_table = _reference_target(table, column)
                                target_logical_id = identity_maps[target_table].get(value)
                                if target_logical_id is None:
                                    raise _invalid()
                                field_name = PACKAGE_COLUMN_EXPORT_DECISIONS[(table, column)]
                                if not field_name.startswith("@"):
                                    data[field_name] = target_logical_id
                                continue
                            if category == "nested_logical_reference":
                                if value is not None:
                                    target_logical_id = nested_story_blocks.get(value)
                                    if target_logical_id is None:
                                        raise _invalid()
                                    data[PACKAGE_COLUMN_EXPORT_DECISIONS[(table, column)]] = target_logical_id
                                continue
                            if category == "polymorphic_logical_reference":
                                source_type = row.get("source_type")
                                target_table = POLYMORPHIC_LOGICAL_REFERENCE_TARGETS[(table, column)].get(source_type)
                                if source_type not in POLYMORPHIC_LOGICAL_REFERENCE_TARGETS[(table, column)]:
                                    raise _invalid()
                                if target_table is not None:
                                    target_logical_id = identity_maps[target_table].get(value)
                                    if target_logical_id is None:
                                        raise _invalid()
                                    data[PACKAGE_COLUMN_EXPORT_DECISIONS[(table, column)]] = target_logical_id
                                continue
                            raise _invalid()

                        if table == "draft_candidates":
                            provenance = _json_value(row["provenance_json"])
                            basis_keys = {
                                "schemaVersion", "outlineRevisionId", "outlineRevision", "outlineHash",
                                "planningRevisionId", "planningRevision", "planningHash", "canonRevision",
                                "projectionRevision", "projectionHash",
                            }
                            if (
                                not isinstance(provenance, dict)
                                or set(provenance) != {"source", "workingDraftRevision", *basis_keys}
                                or provenance.get("source") != "explicit-save-candidate"
                                or provenance.get("workingDraftRevision") != row["working_draft_revision"]
                            ):
                                raise _invalid()
                            source_basis = {key: provenance[key] for key in basis_keys}
                            if row["basis_hash"] != canonical_hash(source_basis):
                                raise _invalid()
                            outline = next((
                                item for item in rows_by_table["chapter_outline_revisions"]
                                if item["id"] == provenance["outlineRevisionId"]
                            ), None)
                            planning = next((
                                item for item in rows_by_table["planning_revisions"]
                                if item["id"] == provenance["planningRevisionId"]
                            ), None)
                            if (
                                outline is None or planning is None
                                or provenance["outlineRevision"] != outline["revision"]
                                or provenance["outlineHash"] != outline["content_hash"]
                                or provenance["planningRevision"] != planning["revision"]
                                or provenance["planningHash"] != planning["content_hash"]
                            ):
                                raise _invalid()
                            provenance["outlineRevisionId"] = identity_maps["chapter_outline_revisions"][outline["id"]]
                            provenance["planningRevisionId"] = identity_maps["planning_revisions"][planning["id"]]
                            data["workingDraftRevision"] = row["working_draft_revision"]
                            data["provenance"] = provenance
                            data["basisHash"] = canonical_hash({key: provenance[key] for key in basis_keys})
                        elif table == "style_contracts":
                            data["payload"] = {
                                "mergedStyle": _json_value(row["merged_style_json"]),
                                "likes": _json_value(row["likes_json"]),
                                "dislikes": _json_value(row["dislikes_json"]),
                            }
                        elif table == "style_contract_template_refs":
                            shared = shared_assets_by_id.get(row["style_template_id"])
                            if shared is None:
                                raise _invalid()
                            data["templateName"] = shared["name"]
                            data["templateRevision"] = shared["revision"]
                        elif table == "creation_contract_experience_refs":
                            shared = shared_assets_by_id.get(row["experience_card_id"])
                            if shared is None:
                                raise _invalid()
                            data["experienceTitle"] = shared["title"]
                            data["experienceRevision"] = shared["revision"]
                        elif table in {"creation_contract_corpus_refs", "creation_contract_corpus_fragment_refs"}:
                            reference = (row["corpus_source_id"], row["source_revision"], row["source_hash"])
                            corpus_logical_id = corpus_logical_ids_by_ref.get(reference)
                            if corpus_logical_id is None:
                                raise _invalid()
                            data["corpusRevisionLogicalId"] = corpus_logical_id
                            if table == "creation_contract_corpus_fragment_refs":
                                data["fragmentOrder"] = row["sort_order"]
                        elif table == "reference_uses":
                            reference = corpus_reference_by_chapter.get((
                                row["corpus_source_id"], row["corpus_chapter_id"]
                            ))
                            if reference is None:
                                raise _invalid()
                            corpus_logical_id = corpus_logical_ids_by_ref.get(reference)
                            if corpus_logical_id is None:
                                raise _invalid()
                            data["corpusRevisionLogicalId"] = corpus_logical_id
                            chapter_logical_id = corpus_chapter_logical_ids.get((
                                corpus_logical_id, row["corpus_chapter_id"],
                            ))
                            if chapter_logical_id is None:
                                raise _invalid()
                            data["corpusChapterLogicalId"] = chapter_logical_id
                        elif table == "market_analyses":
                            evidence = market_evidence_by_analysis.get(row["id"])
                            if evidence is not None:
                                data["snapshotHash"] = evidence["snapshot_hash"]
                                data["timeRange"] = {"capturedAt": evidence["captured_at"]}
                            if row["result_hash"] is not None:
                                data["contentHash"] = row["result_hash"]

                        record = PackageRecord(
                            entity_type=record_type,
                            logical_id=logical_id,
                            revision=_record_revision(row),
                            order=_record_order(row),
                            data=data,
                        )
                        counts[record_type] = counts.get(record_type, 0) + 1
                        if table in {"draft_operation_attempts", "draft_operation_events"}:
                            operation_records.append(record)
                        else:
                            graph_records.append(record)

                referenced_secret_values: list[bytes] = []
                for provider_row in provider_rows:
                    if not isinstance(provider_row, Mapping) or set(provider_row) != {
                        "provider_name", "model_name", "api_key", "base_url"
                    }:
                        raise _invalid()
                    for secret_column in ("api_key", "base_url"):
                        secret_value = provider_row[secret_column]
                        if isinstance(secret_value, str) and secret_value:
                            referenced_secret_values.append(secret_value.encode("utf-8"))
                        elif isinstance(secret_value, bytes) and secret_value:
                            referenced_secret_values.append(bytes(secret_value))
                        elif secret_value not in (None, "", b""):
                            raise _invalid()

                binding_revisions_by_id = {
                    row["id"]: row for row in rows_by_table["project_model_binding_revisions"]
                }
                for item in rows_by_table["project_model_binding_items"]:
                    binding_revision = binding_revisions_by_id.get(item["binding_revision_id"])
                    binding_logical_id = identity_maps["project_model_binding_revisions"].get(
                        item["binding_revision_id"]
                    )
                    if binding_revision is None or binding_logical_id is None:
                        raise _invalid()
                    provider_data = {
                        "taskKey": item["task_key"],
                        "bindingRevisionLogicalId": binding_logical_id,
                        "bindingHash": binding_revision["content_hash"],
                    }
                    if item["provider_name_snapshot"] is not None:
                        provider_data["providerName"] = item["provider_name_snapshot"]
                    if item["model_name_snapshot"] is not None:
                        provider_data["modelName"] = item["model_name_snapshot"]
                    counters["provider-history"] = counters.get("provider-history", 0) + 1
                    provider_history_records.append(PackageRecord(
                        "provider-history",
                        f"provider-history:{counters['provider-history']}",
                        data=provider_data,
                    ))
                    counts["provider-history"] = counts.get("provider-history", 0) + 1

                for record in frozen_asset_records:
                    counts[record.entity_type] = counts.get(record.entity_type, 0) + 1
                for record in corpus_revision_records:
                    counts[record.entity_type] = counts.get(record.entity_type, 0) + 1

                projection_validation: dict[str, object] = {}
                for name, rows in projection_rows.items():
                    hashes: list[str] = []
                    for row in rows:
                        if not isinstance(row, Mapping) or set(row) != {"content_hash"}:
                            raise _invalid()
                        content_hash = row["content_hash"]
                        if not isinstance(content_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", content_hash):
                            raise _invalid()
                        hashes.append(content_hash)
                    projection_validation[name] = {"count": len(hashes), "hashes": tuple(hashes)}

                return ProjectPackageSnapshot(
                    source_project_logical_id=identity_maps["projects"].get(project_id, ""),
                    lifecycle_revision=expected_lifecycle_revision,
                    graph_records=tuple(graph_records),
                    operation_records=tuple(operation_records),
                    provider_history_records=tuple(provider_history_records),
                    frozen_asset_records=tuple(frozen_asset_records),
                    corpus_revision_records=tuple(corpus_revision_records),
                    corpus_blobs=tuple(corpus_blobs),
                    projection_validation=projection_validation,
                    referenced_secret_values=tuple(referenced_secret_values),
                    counts=counts,
                )
            except (KeyError, TypeError, ValueError, UnicodeError, ProjectPackageInvalid):
                raise _invalid() from None
        except (KeyError, TypeError, ValueError, UnicodeError, ProjectPackageInvalid):
            raise _invalid() from None
        finally:
            rollback = getattr(raw, "rollback", None)
            if rollback is not None:
                await rollback()
            self._pool.release(raw)
