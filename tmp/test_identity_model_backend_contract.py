import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import routers.settings_library as settings  # noqa: E402


def test_descriptive_identity_reveal_structures_profile():
    entity = {"name": "木门后老人", "aliases": "[]"}
    profile = {}
    updates = {}
    event = {"chapter_num": 6, "confidence": 0.92, "evidence": "老人承认自己叫宋怀安。"}

    settings._apply_descriptive_identity_reveal_update(
        entity,
        profile,
        updates,
        event,
        "在矿城西区木门后出现的老人，身份不明。",
        "宋怀安，前矿北账务所账房，与陆怀安共事大半年。",
    )

    assert updates["name"] == "宋怀安"
    assert "木门后老人" in settings._decode_json(updates["aliases"])
    assert profile["canonicalName"] == "宋怀安"
    assert any(item["name"] == "木门后老人" and item["status"] == "revealed" for item in profile["personas"])
    assert profile["identityReveals"][0]["fromName"] == "木门后老人"
    assert profile["identityReveals"][0]["toCanonicalName"] == "宋怀安"


def test_codename_reveal_structures_profile():
    entity = {"name": "青先生", "aliases": "[]"}
    profile = {}
    updates = {}
    event = {"chapter_num": 8, "confidence": 0.9, "evidence": "青先生留下徐正清私印。"}

    settings._apply_identity_background_reveal_update(
        entity,
        profile,
        updates,
        event,
        "青先生，身份不明的暗线。",
        "青先生其实是徐正清，曾以化名调度第三密栈。",
    )

    assert updates["name"] == "徐正清"
    assert "青先生" in settings._decode_json(updates["aliases"])
    assert profile["canonicalName"] == "徐正清"
    assert any(item["name"] == "青先生" and item["type"] in {"codename", "alias"} for item in profile["personas"])
    assert profile["identityReveals"][0]["fromName"] == "青先生"


def test_mistaken_identity_claim_does_not_merge():
    profile = {}
    updates = {}
    event = {"chapter_num": 4, "confidence": 0.65, "evidence": "众人只看见背影。"}

    settings._record_identity_claim_or_mistake(
        profile,
        updates,
        event,
        "众人以为黑衣人是陆长庚。",
    )

    assert "name" not in updates
    assert profile["canonicalName"] == "黑衣人"
    assert profile["identityClaims"][0]["claimedAs"] == "陆长庚"
    assert "mistakenIdentities" not in profile


def test_mistaken_identity_disproved_records_mistake():
    profile = {}
    updates = {}
    event = {"chapter_num": 7, "confidence": 0.85, "evidence": "伤痕位置不符。"}

    settings._record_identity_claim_or_mistake(
        profile,
        updates,
        event,
        "黑衣人不是陆长庚。",
    )

    assert "name" not in updates
    assert profile["mistakenIdentities"][0]["mistakenAs"] == "陆长庚"
    assert profile["mistakenIdentities"][0]["status"] == "disproved"


def test_stable_identity_rewrite_not_treated_as_reveal():
    old_value = "徐正清是巡天司主簿，负责北城账册归档。"
    new_value = "徐正清是星债会会主，负责追杀陆沉舟。"

    assert not settings._is_summary_identity_background_reveal(old_value, new_value, "")
    assert not settings._allows_layered_hard_field_reveal(old_value, new_value, "")


if __name__ == "__main__":
    test_descriptive_identity_reveal_structures_profile()
    test_codename_reveal_structures_profile()
    test_mistaken_identity_claim_does_not_merge()
    test_mistaken_identity_disproved_records_mistake()
    test_stable_identity_rewrite_not_treated_as_reveal()
    print("identity model backend contract passed")
