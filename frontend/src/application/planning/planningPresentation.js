const id = node => String(node?.id || node?.clientNodeKey || '')
const text = value => Array.isArray(value) ? value.join('、') : String(value ?? '')
const sections = { volumes: '分卷', plots: '情节线', 'story-blocks': '故事块' }
const fields = {
  volumes: { coreChange: '本卷核心变化', mainPressure: '主要压力', ensembleFocus: '人物与群像', forbiddenEvents: '不可提前发生' },
  plots: { plotType: '类型', storyQuestion: '长期问题', futureDirection: '推进方向', expectedPayoff: '预期回报', relatedCharacters: '关联人物' },
  'story-blocks': { entrySituation: '进入情境', blockGoal: '故事块目标', mainPressure: '主要压力', expectedChange: '预期变化', openQuestions: '待解问题', involvedCharacters: '涉及人物' },
}
const designLabels = { displayName: '人物', role: '角色', summary: '概述', nodes: '变化节点', title: '节点名称', stage: '阶段', goal: '目标', belief: '信念', relationship: '关系', ability: '能力', expectedChapter: '预计章节' }
function designText(value) {
  if (Array.isArray(value)) return value.map(designText).join('\n\n')
  if (value && typeof value === 'object') return Object.entries(value)
    .filter(([key]) => !['id', 'revision', 'contentHash', 'clientNodeKey'].includes(key))
    .map(([key, item]) => `${designLabels[key] || key}：${designText(item)}`).join('\n')
  return text(value)
}
const relation = (items, key) => {
  const node = (items || []).find(node => id(node) === String(key))
  return node ? `${node.title || '未命名'}${node.lifecycle === 'retired' ? ' · 已退役' : ''}` : '未关联'
}

// Both inputs use canonicalPlanningContentForUi; display selection never updates activeStoryBlockRef.
export function planningEntries(content, section, { includeRetired = false } = {}) {
  const key = section === 'story-blocks' ? 'storyBlocks' : section
  return (content?.[key] || []).filter(node => includeRetired || node.lifecycle !== 'retired').map((node, index) => {
    const details = Object.entries(fields[section] || {}).map(([name, label]) => ({ label, value: text(node[name]) || '尚未填写' }))
    if (section === 'plots' && node.characterDesign) details.push({ label: '人物变化计划', value: designText(node.characterDesign) })
    if (section === 'story-blocks') {
      details.unshift({ label: '所属分卷', value: relation(content.volumes, node.volumeRef) },
        { label: '关联情节线', value: (node.plotRefs || []).map(key => relation(content.plots, key)).join('、') || '未关联' })
      for (const [stageIndex, stage] of (node.stages || []).entries()) {
        if (!includeRetired && stage.lifecycle === 'retired') continue
        details.push({ label: `阶段 ${stageIndex + 1} · ${stage.title || '未命名'}`, value: [
          stage.lifecycle === 'retired' ? '已停用' : '',
          `目的：${stage.purpose || '尚未填写'}`, `戏剧问题：${stage.dramaticQuestion || '尚未填写'}`,
          ...(stage.sceneTasks || []).filter(task => includeRetired || task.lifecycle !== 'retired').map((task, i) =>
            `任务 ${i + 1}${task.lifecycle === 'retired' ? '（已停用）' : ''}：${task.task || '尚未填写'}\n完成依据：${task.completionEvidence || '尚未填写'}`),
        ].filter(Boolean).join('\n') })
      }
    }
    return { key: id(node), title: node.title || `未命名${sections[section]}`, order: node.order ?? index + 1,
      lifecycle: node.lifecycle, current: section === 'story-blocks' && id(node) === String(content.activeStoryBlockRef), fields: details }
  })
}

export function comparePlanning(before, after) {
  const changes = []
  for (const section of Object.keys(sections)) {
    const left = planningEntries(before, section, { includeRetired: true })
    const right = planningEntries(after, section, { includeRetired: true })
    for (const key of new Set([...left, ...right].map(row => row.key))) {
      const original = left.find(row => row.key === key), proposed = right.find(row => row.key === key)
      // Active selection is compared separately as an execution arrangement.
      const withoutSelection = row => row && Object.fromEntries(Object.entries(row).filter(([name]) => name !== 'current'))
      if (JSON.stringify(withoutSelection(original)) === JSON.stringify(withoutSelection(proposed))) continue
      changes.push({ key: `${section}:${key}`, section: sections[section], title: proposed?.title || original.title,
        kind: !original ? '新增' : !proposed ? '移除' : '调整', before: original, after: proposed })
    }
  }
  if ((before?.activeStoryBlockRef || '') !== (after?.activeStoryBlockRef || '')) {
    const row = content => ({ title: relation(content?.storyBlocks, content?.activeStoryBlockRef), fields: [] })
    changes.push({ key: 'active-story-block', title: '当前故事块', section: '执行安排', kind: '调整', before: row(before), after: row(after) })
  }
  return changes
}
