import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tmp"))

import audit_state_source_stability as audit  # noqa: E402


def test_unresolved_refs_are_governed_by_type_and_explanation():
    characters = [
        {"id": "char-xu", "name": "徐主簿（巡天司主簿）", "role": "supporting"},
        {"id": "char-zhou", "name": "周远（老周）", "role": "supporting"},
    ]
    entities = [
        {
            "id": "xu-setting",
            "entity_type": "character",
            "name": "徐主簿",
            "aliases": "[]",
            "profile": "{}",
        },
        {"id": "org-xuntian", "entity_type": "faction", "name": "巡天司", "aliases": "[]", "profile": "{}"},
        {"id": "org-shang", "entity_type": "faction", "name": "商盟", "aliases": "[]", "profile": "{}"},
    ]
    facts = [
        {"id": "fact-org-1", "chapter_num": 1, "related_characters": '["巡天司"]', "content": "巡天司开始追查。"},
        {"id": "fact-org-2", "chapter_num": 1, "related_characters": '["商盟"]', "content": "商盟放出消息。"},
        {"id": "fact-title", "chapter_num": 2, "related_characters": '["巡天司主簿"]', "content": "巡天司主簿留下印记。"},
        {"id": "fact-real-name", "chapter_num": 3, "related_characters": '["徐正清"]', "content": "徐正清身份线推进。"},
        {"id": "fact-nickname", "chapter_num": 4, "related_characters": '["老周"]', "content": "老周的消息被提及。"},
        {"id": "fact-relation-1", "chapter_num": 4, "related_characters": '["老周的儿子"]', "content": "老周的儿子出面。"},
        {"id": "fact-relation-2", "chapter_num": 5, "related_characters": '["小九的父亲"]', "content": "小九的父亲身份待查。"},
        {"id": "fact-unknown", "chapter_num": 5, "related_characters": '["陌生瓦匠"]', "content": "陌生瓦匠递话。"},
    ]

    identity = audit.summarize_identity_model(entities, facts, characters)
    governance = identity["unresolvedCharacterRefGovernance"]
    merge = identity["characterArcMergeBeforeAfter"]

    assert merge["charactersTableRawCount"] == 2
    assert merge["settingCharacterEntityCount"] == 1
    assert merge["canonicalPersonCountAfterMerge"] == 1
    assert merge["noFactIsolatedPersonCount"] == 1

    assert governance["beforeCount"] == 8
    assert governance["afterCount"] == 1
    assert {item["name"] for item in governance["organizationRefs"]} == {"巡天司", "商盟"}
    assert {item["name"] for item in governance["mergedCharacterRefs"]} >= {"巡天司主簿", "徐正清"}
    assert {item["name"] for item in governance["pendingRelationshipRefs"]} >= {"老周", "老周的儿子", "小九的父亲"}
    assert governance["unresolvedCharacterRefs"] == [{"name": "陌生瓦匠", "count": 1}]


if __name__ == "__main__":
    test_unresolved_refs_are_governed_by_type_and_explanation()
    print("state source audit identity contract passed")
