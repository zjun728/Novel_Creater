"""路由公共工具：camelCase ↔ snake_case 转换"""
import json
import re
import time

# 布尔字段列表（snake_case），MySQL TINYINT → Python bool
BOOL_FIELDS = {'stream', 'supports_json', 'supports_streaming', 'is_hidden', 'no_direct_imitation'}

JSON_FIELDS = {
    'thinking',
    'writing_profile',
    'forbidden_directions',
    'far_vision',
    'current_volume',
    'near_chapters',
    'hard_state',
    'soft_state',
    'related_characters',
    'possible_resolve_window',
    'resolve_options',
    'related_plot_threads',
    'tags',
    'extracted_hooks',
    'extracted_appeals',
    'metadata',
    'content_json',
    'aliases',
    'profile',
    'key_characters',
    'foreshadowing_plan',
    'unresolved_items',
    'stage_summary_report',
    'audit_report',
    'report_json',
    'chapter_refs',
    'related_items',
    'key_characters',
    'stage_plan',
    'completed_stages',
    'unresolved_questions',
    'dont_advance_yet',
    'carry_over_to_next_chapter',
    'lock_state',
    'review_history',
    'review_json',
    'block_stage_snapshot',
    'chunk_ids',
    'genre_tags',
    'avoid_patterns',
    'abstract_notes_json',
    'metrics_json',
    'safety_flags',
    'source_card_ids',
    'merged_guidance',
    'audit_focus',
    'safety_policy',
    'guidance_json',
}

# 首字母缩写映射：snake_case 部分 → camelCase 中正确的大小写
ACRONYMS = {
    'url': 'URL',
    'api': 'API',
    'json': 'JSON',
    'id': 'Id',
}

# camelCase → snake_case：处理连续大写字母（如 baseURL → base_url）
_SNAKE_RE = re.compile(r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])')

def to_snake(camel):
    return _SNAKE_RE.sub('_', camel).lower()

def _acronym_part(part):
    return ACRONYMS.get(part.lower(), part.title())

def to_camel(snake):
    parts = snake.split('_')
    return parts[0] + ''.join(_acronym_part(p) for p in parts[1:])

def _decode_json_field(value):
    if isinstance(value, (bytes, bytearray)):
        value = value.decode('utf-8')
    if value is None or not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value

def convert_row(r):
    if not r: return None
    result = {}
    for k, v in r.items():
        key = to_camel(k)
        if k in BOOL_FIELDS:
            result[key] = bool(v)
        elif k in JSON_FIELDS:
            result[key] = _decode_json_field(v)
        else:
            result[key] = v
    return result

def convert_rows(rows):
    if not rows: return []
    return [convert_row(r) for r in rows]

async def touch_project(pid: str):
    from database import execute
    await execute("UPDATE projects SET updated_at=%s WHERE id=%s", (int(time.time() * 1000), pid))
