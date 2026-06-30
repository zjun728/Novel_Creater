import importlib
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def assert_contains(text: str, needle: str, label: str) -> None:
    assert needle in text, f"missing {label}: {needle}"


def test_backend_exposes_prompt_micro_demo_seed_route_and_safe_mapping():
    router_py = read("backend/routers/experience_cards.py")
    api_client = read("frontend/src/api/db/client.js")
    view_vue = read("frontend/src/views/ExperienceCardsView.vue")

    assert_contains(router_py, "_ensure_builtin_experience_cards", "automatic built-in experience card initialization")
    assert_contains(router_py, "_ensure_builtin_writing_standards", "automatic built-in writing standard initialization")
    assert_contains(router_py, "PROMPT_MICRO_DEMO_DATA_DIR", "stable prompt card data directory")
    assert_contains(router_py, "sampleMicroDemoCards.v2_1.json", "v2.1 stable card import file")
    assert_contains(router_py, "sampleMicroDemoCards.v2_2.json", "v2.2 stable card import file")
    assert_contains(router_py, "prompt_injectable_scene", "scene card type")
    assert_contains(router_py, "prompt_injectable_dialogue", "dialogue card type")
    assert_contains(router_py, "prompt-ready-low-dose", "prompt-ready status")
    assert_contains(router_py, "backend-reference-only-until-reviewed", "backend-only status")
    assert_contains(api_client, "experienceCards", "frontend API namespace")
    assert "导入微示范卡" not in view_vue, "formal product UI must not expose manual prompt-card import"
    assert "迁移本地样本报告" not in view_vue, "formal product UI must not expose old local report migration"

    forbidden_prompt_fields = [
        "sourceWork",
        "sourceInfluence",
        "sourceCardId",
        "characterEmotionVariants",
        "emotionDialogueOptions",
    ]
    for field in forbidden_prompt_fields:
        assert_contains(router_py, field, f"backend strips {field}")


def test_prompt_micro_demo_normalizer_strips_backend_only_fields():
    module = importlib.import_module("routers.experience_cards")
    cards = module._load_prompt_micro_demo_cards()

    assert len([card for card in cards if card["version"] == "v2.1"]) == 16
    assert len([card for card in cards if card["version"] == "v2.2"]) == 12

    prompt_ready = [card for card in cards if card["prompt_readiness"] == "prompt-ready-low-dose"]
    backend_only = [card for card in cards if card["prompt_readiness"] == "backend-reference-only-until-reviewed"]
    assert prompt_ready, "prompt-ready cards should be available for selector diagnostics"
    assert backend_only, "backend-reference-only cards should be imported for display and diagnostics"

    serialized = json.dumps(cards, ensure_ascii=False)
    for forbidden in [
        "sourceWork",
        "sourceInfluence",
        "sourceCardId",
        "characterEmotionVariants",
        "emotionDialogueOptions",
        "凡人修仙传",
        "四世同堂",
        "一句顶一万句",
        "修真聊天群",
        "韩立",
        "黄枫谷",
        "祁家",
    ]:
        assert forbidden not in serialized, f"normalized prompt micro demo cards leaked {forbidden}"

    assert any(re.search(r"prompt_injectable_dialogue", card["card_type"]) for card in cards)
    assert all(card["source_fields_stripped"] is True for card in cards)


if __name__ == "__main__":
    test_backend_exposes_prompt_micro_demo_seed_route_and_safe_mapping()
    test_prompt_micro_demo_normalizer_strips_backend_only_fields()
