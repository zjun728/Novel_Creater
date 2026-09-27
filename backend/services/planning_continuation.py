"""Read-only decisions shared by the continuation UI and generation guards."""
from backend.domain.planning_completion import missing_block_fields, missing_volume_fields
from backend.domain.planning_expansion import node_ref
from backend.services.planning_progress import planning_progress_reason


def inspect_continuation(plan, authority, *, draft_changed=False, archived=False,
                         basis_ready=True, generation_pending=False):
    result = {'status': 'ready', 'message': '', 'currentVolume': None, 'currentBlock': None,
              'targetVolume': None, 'targetBlock': None, 'missing': [], 'actions': []}

    def stop(status, message):
        result.update(status=status, message=message)
        return result

    def summary(node):
        return {'id': node_ref(node), 'title': node.title} if node else None

    if plan:
        active = next((b for b in plan.story_blocks if node_ref(b) == plan.active_story_block_ref), None)
        volume = next((v for v in plan.volumes if active and node_ref(v) == active.volume_ref), None)
        result.update(currentBlock=summary(active), currentVolume=summary(volume))
    else:
        active = volume = None
    if archived: return stop('archived', '项目已归档，可以阅读安排，不能生成或采用。')
    if not basis_ready: return stop('foundation_pending', '请先确认当前创作基础。')
    projection = authority.get('projection')
    if not projection or projection['canon_revision_number'] != projection['projection_revision_number']:
        return stop('sync_pending', '进度尚未同步；查询只读取状态，不会主动修复或重复定稿。')
    if generation_pending: return stop('generation_pending', '原规划操作仍在进行，请先核对原操作。')
    if authority.get('activeSession') is not None:
        return stop('chapter_active', '当前章节正在创作，请先处理当前章节，再准备后续安排。')
    if draft_changed: return stop('draft_pending', '已有待处理工作稿，请先查看、编辑或确认；检查不会覆盖它。')
    if not active or not volume: return stop('initial_pending', '尚无可承接的正式规划，请先准备并确认首次故事规划。')
    reason = planning_progress_reason(authority.get('current')) if authority.get('current') else None
    if reason not in {'activeStoryBlockCompleted', 'activeStoryBlockTasksCompleted'}:
        return stop('block_active', '当前故事块尚未完成；完成本块的场景任务并定稿后再准备后续安排。')

    following = sorted((b for b in plan.story_blocks if b.lifecycle == 'active'
                        and b.volume_ref == active.volume_ref and b.order > active.order), key=lambda b: b.order)

    def action(mode, label, kind):
        result['actions'].append({'mode': mode, 'label': label, 'kind': kind})

    if following:
        block = following[0]
        missing = missing_block_fields(block)
        result.update(targetVolume=summary(volume), targetBlock=summary(block), missing=missing)
        result['message'] = f'已有后续故事块「{block.title}」，' + ('请先补全缺项。' if missing else '可核对后采用，无需重复生成。')
        action('fill_next_block' if missing else 'next_block', 'AI 补全故事块' if missing else '查看并采用', 'fill' if missing else 'reuse')
        return result

    action('next_block', '生成下一故事块', 'generate')
    later = sorted((v for v in plan.volumes if v.lifecycle == 'active' and v.order > volume.order), key=lambda v: v.order)
    if not later:
        result['message'] = '当前卷没有后续故事块。可继续本卷；若决定结束本卷，可准备下一卷。'
        action('next_volume', '准备下一卷', 'generate')
        return result
    target = later[0]
    blocks = sorted((b for b in plan.story_blocks if b.lifecycle == 'active' and b.volume_ref == node_ref(target)), key=lambda b: b.order)
    block = blocks[0] if blocks else None
    missing = missing_volume_fields(target) + (missing_block_fields(block) if block else ['首个故事块'])
    result.update(targetVolume=summary(target), targetBlock=summary(block), missing=missing)
    result['message'] = f'当前卷无后续块；下一卷「{target.title}」已存在。可继续本卷，或核对下一卷的安排。'
    fill = bool(missing_volume_fields(target) or (block and missing_block_fields(block)))
    action('fill_next_volume' if fill else 'next_volume', 'AI 补全下一卷安排' if fill else ('查看并采用下一卷' if block else '生成下一卷首个故事块'),
           'fill' if fill else ('reuse' if block else 'generate'))
    return result
