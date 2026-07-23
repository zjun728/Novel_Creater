from __future__ import annotations

from dataclasses import dataclass

import aiomysql
import pytest

from backend.tests.integration.test_schema_bootstrap import (
    BINDING_ID,
    HASH_A,
    HASH_B,
    HASH_C,
    NOW,
    PROJECT_ID,
    _insert_active_provider,
    _insert_revision_one_contracts,
    _insert_selection_revision,
)


SEED_ID = "00000000-0000-0000-0000-000000000040"
SEED_REVISION_ID = "00000000-0000-0000-0000-000000000041"
SEED_B_ID = "00000000-0000-0000-0000-000000000050"
SEED_B_REVISION_ID = "00000000-0000-0000-0000-000000000051"
SEED_B_HASH = "d" * 64


@dataclass(frozen=True)
class ContractBasis:
    selection_revision: int
    contract_revision: int
    seed_id: str
    seed_revision_id: str
    seed_hash: str
    creation_contract_id: str
    creation_hash: str
    style_contract_id: str
    style_hash: str


async def _insert_first_basis(session) -> ContractBasis:
    creation_id, style_id = await _insert_revision_one_contracts(session)
    return ContractBasis(
        1,
        1,
        SEED_ID,
        SEED_REVISION_ID,
        HASH_A,
        creation_id,
        HASH_B,
        style_id,
        HASH_C,
    )


async def _insert_seed_revision(
    session,
    *,
    seed_id: str,
    seed_revision_id: str,
    seed_hash: str,
) -> None:
    await session.execute(
        """INSERT INTO creative_seeds
           (id,project_id,status,created_at,updated_at)
           VALUES (%s,%s,'candidate',%s,%s)""",
        (seed_id, PROJECT_ID, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO creative_seed_revisions
           (id,project_id,seed_id,revision,payload_json,content_hash,created_at)
           VALUES (%s,%s,%s,1,'{}',%s,%s)""",
        (seed_revision_id, PROJECT_ID, seed_id, seed_hash, NOW),
    )
    await session.execute(
        """INSERT INTO creative_seed_heads
           (seed_id,revision_id,revision,content_hash,updated_at)
           VALUES (%s,%s,1,%s,%s)""",
        (seed_id, seed_revision_id, seed_hash, NOW),
    )


async def _insert_later_basis(
    session,
    *,
    revision: int,
    seed_id: str,
    seed_revision_id: str,
    seed_hash: str,
    creation_contract_id: str,
    creation_hash: str,
    style_contract_id: str,
    style_hash: str,
) -> ContractBasis:
    await _insert_selection_revision(
        session,
        seed_id=seed_id,
        seed_revision_id=seed_revision_id,
        seed_hash=seed_hash,
        selection_revision=revision,
    )
    changed = await session.execute(
        """UPDATE project_selected_seeds
              SET seed_id=%s,seed_revision_id=%s,seed_hash=%s,
                  selection_revision=%s,selected_at=%s,updated_at=%s
            WHERE project_id=%s AND selection_revision=%s""",
        (
            seed_id,
            seed_revision_id,
            seed_hash,
            revision,
            NOW,
            NOW,
            PROJECT_ID,
            revision - 1,
        ),
    )
    assert changed == 1
    await session.execute(
        """INSERT INTO creation_contracts
           (id,project_id,revision,selection_revision,seed_id,seed_revision_id,
            seed_hash,binding_revision_id,binding_hash,channel_profile_key,
             genre_profile_key,quality_charter_version,total_word_min,
             total_word_max,chapter_capacity_policy,reference_manifest_json,
             reference_manifest_hash,content_json,content_hash,confirmed_at)
           SELECT %s,project_id,%s,%s,%s,%s,%s,
                   binding_revision_id,binding_hash,channel_profile_key,
                   genre_profile_key,quality_charter_version,total_word_min,
                   total_word_max,chapter_capacity_policy,reference_manifest_json,
                  reference_manifest_hash,content_json,%s,confirmed_at
             FROM creation_contracts WHERE project_id=%s AND revision=1""",
        (
            creation_contract_id,
            revision,
            revision,
            seed_id,
            seed_revision_id,
            seed_hash,
            creation_hash,
            PROJECT_ID,
        ),
    )
    await session.execute(
        """INSERT INTO style_contracts
           (id,project_id,creation_contract_id,revision,merged_style_json,
            likes_json,dislikes_json,content_hash,confirmed_at)
           VALUES (%s,%s,%s,%s,'{}','[]','[]',%s,%s)""",
        (
            style_contract_id,
            PROJECT_ID,
            creation_contract_id,
            revision,
            style_hash,
            NOW,
        ),
    )
    return ContractBasis(
        revision,
        revision,
        seed_id,
        seed_revision_id,
        seed_hash,
        creation_contract_id,
        creation_hash,
        style_contract_id,
        style_hash,
    )


async def _insert_draft(
    session,
    *,
    draft_id: str,
    draft_hash: str,
    basis: ContractBasis,
    active_slot: int | None = 1,
) -> None:
    await session.execute(
        """INSERT INTO project_bible_drafts
           (id,project_id,active_slot,base_head_revision,selection_revision,
            seed_id,seed_revision_id,seed_hash,contract_revision,
            creation_contract_id,creation_hash,style_contract_id,style_hash,
            binding_revision_id,binding_hash,policy_version,draft_json,
            content_hash,draft_version,created_at,updated_at)
           VALUES (%s,%s,%s,0,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                   'bible-policy-v1','{}',%s,1,%s,%s)""",
        (
            draft_id,
            PROJECT_ID,
            active_slot,
            basis.selection_revision,
            basis.seed_id,
            basis.seed_revision_id,
            basis.seed_hash,
            basis.contract_revision,
            basis.creation_contract_id,
            basis.creation_hash,
            basis.style_contract_id,
            basis.style_hash,
            BINDING_ID,
            HASH_A,
            draft_hash,
            NOW,
            NOW,
        ),
    )


async def _insert_confirmation_request(
    session,
    *,
    request_id: str,
    draft_id: str,
    draft_hash: str,
    basis: ContractBasis,
    status: str,
) -> None:
    failed = status == "failed"
    await session.execute(
        """INSERT INTO bible_confirmation_requests
           (id,project_id,selection_revision,contract_revision,
            creation_contract_id,creation_hash,style_contract_id,style_hash,
            draft_id,draft_version,draft_hash,idempotency_key,request_hash,
            status,bible_revision_id,result_revision,result_hash,
            public_error_code,created_at,completed_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s,%s,
                   NULL,NULL,NULL,%s,%s,%s)""",
        (
            request_id,
            PROJECT_ID,
            basis.selection_revision,
            basis.contract_revision,
            basis.creation_contract_id,
            basis.creation_hash,
            basis.style_contract_id,
            basis.style_hash,
            draft_id,
            draft_hash,
            request_id.replace("-", "").ljust(64, "0")[:64],
            draft_hash,
            status,
            "confirmation_failed" if failed else None,
            NOW,
            NOW if failed else None,
        ),
    )


@pytest.mark.mysql
async def test_active_draft_slot_moves_across_seed_reselection_without_deleting_history(
    disposable_mysql,
):
    session = disposable_mysql.session
    basis_a = await _insert_first_basis(session)
    draft_a = "10000000-0000-0000-0000-000000000001"
    draft_b = "10000000-0000-0000-0000-000000000002"
    draft_c = "10000000-0000-0000-0000-000000000003"
    request_a = "20000000-0000-0000-0000-000000000001"

    await _insert_draft(session, draft_id=draft_a, draft_hash="1" * 64, basis=basis_a)
    await _insert_confirmation_request(
        session,
        request_id=request_a,
        draft_id=draft_a,
        draft_hash="1" * 64,
        basis=basis_a,
        status="reserved",
    )
    await session.execute(
        "UPDATE project_bible_drafts SET active_slot=NULL WHERE id=%s",
        (draft_a,),
    )

    await _insert_seed_revision(
        session,
        seed_id=SEED_B_ID,
        seed_revision_id=SEED_B_REVISION_ID,
        seed_hash=SEED_B_HASH,
    )
    basis_b = await _insert_later_basis(
        session,
        revision=2,
        seed_id=SEED_B_ID,
        seed_revision_id=SEED_B_REVISION_ID,
        seed_hash=SEED_B_HASH,
        creation_contract_id="30000000-0000-0000-0000-000000000002",
        creation_hash="2" * 64,
        style_contract_id="40000000-0000-0000-0000-000000000002",
        style_hash="3" * 64,
    )
    await _insert_draft(session, draft_id=draft_b, draft_hash="4" * 64, basis=basis_b)
    await session.execute(
        "UPDATE project_bible_drafts SET active_slot=NULL WHERE id=%s",
        (draft_b,),
    )

    basis_c = await _insert_later_basis(
        session,
        revision=3,
        seed_id=SEED_ID,
        seed_revision_id=SEED_REVISION_ID,
        seed_hash=HASH_A,
        creation_contract_id="30000000-0000-0000-0000-000000000003",
        creation_hash="5" * 64,
        style_contract_id="40000000-0000-0000-0000-000000000003",
        style_hash="6" * 64,
    )
    await _insert_draft(session, draft_id=draft_c, draft_hash="7" * 64, basis=basis_c)

    rows = await session.fetchall(
        """SELECT id,active_slot,selection_revision,seed_id
             FROM project_bible_drafts WHERE project_id=%s ORDER BY id""",
        (PROJECT_ID,),
    )
    selections = await session.fetchall(
        """SELECT selection_revision,seed_id,seed_revision_id,seed_hash
             FROM project_seed_selection_revisions
            WHERE project_id=%s ORDER BY selection_revision""",
        (PROJECT_ID,),
    )
    selected = await session.fetchone(
        """SELECT selection_revision,seed_id,seed_revision_id,seed_hash
             FROM project_selected_seeds WHERE project_id=%s""",
        (PROJECT_ID,),
    )
    request = await session.fetchone(
        "SELECT draft_id,draft_version,draft_hash FROM bible_confirmation_requests WHERE id=%s",
        (request_a,),
    )
    assert rows == [
        {"id": draft_a, "active_slot": None, "selection_revision": 1, "seed_id": SEED_ID},
        {"id": draft_b, "active_slot": None, "selection_revision": 2, "seed_id": SEED_B_ID},
        {"id": draft_c, "active_slot": 1, "selection_revision": 3, "seed_id": SEED_ID},
    ]
    assert selections == [
        {
            "selection_revision": 1,
            "seed_id": SEED_ID,
            "seed_revision_id": SEED_REVISION_ID,
            "seed_hash": HASH_A,
        },
        {
            "selection_revision": 2,
            "seed_id": SEED_B_ID,
            "seed_revision_id": SEED_B_REVISION_ID,
            "seed_hash": SEED_B_HASH,
        },
        {
            "selection_revision": 3,
            "seed_id": SEED_ID,
            "seed_revision_id": SEED_REVISION_ID,
            "seed_hash": HASH_A,
        },
    ]
    assert selected == selections[-1]
    assert request == {
        "draft_id": draft_a,
        "draft_version": 1,
        "draft_hash": "1" * 64,
    }


@pytest.mark.mysql
async def test_failed_confirmation_keeps_active_draft_editable(disposable_mysql):
    session = disposable_mysql.session
    basis = await _insert_first_basis(session)
    draft_id = "10000000-0000-0000-0000-000000000011"
    request_id = "20000000-0000-0000-0000-000000000011"
    original_hash = "8" * 64
    updated_hash = "9" * 64

    await _insert_draft(
        session,
        draft_id=draft_id,
        draft_hash=original_hash,
        basis=basis,
    )
    await _insert_confirmation_request(
        session,
        request_id=request_id,
        draft_id=draft_id,
        draft_hash=original_hash,
        basis=basis,
        status="failed",
    )
    await session.execute(
        """UPDATE project_bible_drafts
              SET draft_json='{"updated": true}',content_hash=%s,
                  draft_version=2,updated_at=%s
            WHERE id=%s AND active_slot=1""",
        (updated_hash, NOW + 1, draft_id),
    )

    draft = await session.fetchone(
        "SELECT active_slot,draft_version,content_hash FROM project_bible_drafts WHERE id=%s",
        (draft_id,),
    )
    request = await session.fetchone(
        "SELECT status,draft_version,draft_hash FROM bible_confirmation_requests WHERE id=%s",
        (request_id,),
    )
    assert draft == {
        "active_slot": 1,
        "draft_version": 2,
        "content_hash": updated_hash,
    }
    assert request == {
        "status": "failed",
        "draft_version": 1,
        "draft_hash": original_hash,
    }


@pytest.mark.mysql
async def test_database_rejects_a_second_active_draft_for_one_project(
    disposable_mysql,
):
    session = disposable_mysql.session
    basis = await _insert_first_basis(session)
    await _insert_draft(
        session,
        draft_id="10000000-0000-0000-0000-000000000021",
        draft_hash="a" * 64,
        basis=basis,
    )

    with pytest.raises(aiomysql.IntegrityError):
        await _insert_draft(
            session,
            draft_id="10000000-0000-0000-0000-000000000022",
            draft_hash="b" * 64,
            basis=basis,
        )


@pytest.mark.mysql
async def test_generation_attempt_check_enforces_owned_leases_and_terminal_cleanup(
    disposable_mysql,
):
    session = disposable_mysql.session
    basis = await _insert_first_basis(session)
    provider_id = "50000000-0000-0000-0000-000000000001"
    await _insert_active_provider(session, provider_id, "Bible schema provider")
    columns = (
        "id,project_id,selection_revision,seed_id,seed_revision_id,seed_hash,"
        "contract_revision,creation_contract_id,creation_hash,style_contract_id,"
        "style_hash,binding_revision_id,binding_hash,provider_id,model_name_snapshot,"
        "policy_version,idempotency_key,request_hash,input_manifest_json,"
        "input_manifest_hash,status,owner_token,lease_expires_at,attempt_version,"
        "result_json,result_hash,public_error_code,created_at,completed_at"
    )
    placeholders = ",".join(("%s",) * 29)

    await session.execute(
        f"INSERT INTO bible_generation_attempts ({columns}) VALUES ({placeholders})",
        (
            "60000000-0000-0000-0000-000000000001",
            PROJECT_ID,
            basis.selection_revision,
            SEED_ID,
            SEED_REVISION_ID,
            HASH_A,
            basis.contract_revision,
            basis.creation_contract_id,
            basis.creation_hash,
            basis.style_contract_id,
            basis.style_hash,
            BINDING_ID,
            HASH_A,
            provider_id,
            "model",
            "bible-policy-v1",
            "c" * 64,
            "d" * 64,
            "{}",
            "e" * 64,
            "running",
            "70000000-0000-0000-0000-000000000001",
            NOW + 10_000,
            1,
            None,
            None,
            None,
            NOW,
            None,
        ),
    )

    with pytest.raises(aiomysql.OperationalError, match="Check constraint"):
        await session.execute(
            f"INSERT INTO bible_generation_attempts ({columns}) VALUES ({placeholders})",
            (
                "60000000-0000-0000-0000-000000000002",
                PROJECT_ID,
                basis.selection_revision,
                SEED_ID,
                SEED_REVISION_ID,
                HASH_A,
                basis.contract_revision,
                basis.creation_contract_id,
                basis.creation_hash,
                basis.style_contract_id,
                basis.style_hash,
                BINDING_ID,
                HASH_A,
                provider_id,
                "model",
                "bible-policy-v1",
                "f" * 64,
                "0" * 64,
                "{}",
                "1" * 64,
                "succeeded",
                "70000000-0000-0000-0000-000000000002",
                NOW + 10_000,
                1,
                "{}",
                "2" * 64,
                None,
                NOW,
                NOW,
            ),
        )
