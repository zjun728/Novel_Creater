# Author-facing Planning Status Design

**Date:** 2026-08-29
**Status:** Approved
**Product slice:** Author-facing Canon/Projection and Bible status presentation

## 1. Purpose

Novel Creator already lets an author move between project stages through the
left sidebar, and completed stages already identify the current next step where
needed. This slice does not add automatic navigation or a new stage-handoff
system. It removes implementation-shaped status from the author interface while
preserving useful confirmation that finalized chapters have updated planning
progress.

The product audit used the existing project `典镇山河` at 1440×900 and browser
zoom 100%. It found two author-facing defects:

1. Story Planning renders `Canon R…`, `Projection R…`, internal subject keys,
   field paths, UUIDs, and serialized JSON under “正文已发生”.
2. A confirmed Creation Bible renders the internal reason code
   `bible_confirmed` through a fallback label even though the page already shows
   the correct confirmed-baseline state.

## 2. User-approved interaction boundary

- Keep the left sidebar as the way authors freely switch project modules.
- Do not automatically navigate after selecting a seed, signing a contract,
  confirming a Bible, confirming planning, or completing another stage.
- Do not add stage-handoff buttons or redesign the project information
  architecture in this slice.
- Do not change any save, confirm, generation, finalization, Canon, Projection,
  planning, or routing authority.
- Do not add Provider calls, database writes, migrations, or new backend routes.
- Validate only the approved wide-screen target: headed Chromium at 1440×900,
  browser zoom 100%. Mobile portrait and 200% zoom are outside this slice.

## 3. Chosen approach

Use an author-facing presentation adapter in front of the existing Planning
state. The adapter recognizes only the closed story-progress shapes the product
already creates, joins their target IDs to author-authored Planning nodes in
memory, and emits a small display model. The component renders only that display
model. It never renders arbitrary progress values or falls back to internal
identifiers.

This preserves the separation between actual finalized progress and future
planning while removing the diagnostic surface. It is preferable to a folded
“diagnostic information” disclosure because internal values still would be one
click away from the author flow. It is preferable to deleting the panel because
authors still need confirmation that finalization changed project progress.

## 4. Planning progress presentation

### 4.1 Component contract

`ActualProgressPanel.vue` remains a read-only component. It receives:

- the existing `actualProgress` items;
- the existing Canon/Projection synchronization status; and
- the currently displayed Planning content so target IDs can be resolved to
  author-authored node labels.

A focused application helper builds immutable presentation values. The Vue
component does not stringify arbitrary values or concatenate IDs. The helper
may inspect technical fields only to validate origin and correlation; those
fields never enter its display model.

### 4.2 Recognized progress

A progress entry is presentable only when all of these are true:

- `value` is a plain object with exactly `targetType`, `targetId`, `status`, and
  `chapterNumber` as own enumerable fields;
- those four fields have the expected scalar types;
- `targetType` is exactly `story_block`, `stage`, or `scene_task`, matching the
  backend `ProgressTargetType` domain;
- `status` is exactly `started`, `advanced`, or `completed`;
- `chapterNumber` is a positive safe integer; and
- `entityId` is `null` and `subjectKey` is exactly `__global__`;
- `fieldPath` is exactly `plot.progress.${targetType}.${targetId}`; and
- `targetId` resolves to a node in the current Planning aggregate.

The visible row contains only:

- `第 N 章`;
- the Chinese target kind (`故事块`, `阶段`, or `场景任务`);
- an author-text hierarchy resolved from the aggregate (`故事块`,
  `故事块 / 阶段`, or `故事块 / 阶段 / 场景任务`); and
- a fixed Chinese status label: `started → 已开始`, `advanced → 已推进`, or
  `completed → 已完成`.

The matched label must come only from the Planning node's existing `title` or
`task` field. An absent or blank label becomes the fixed text `当前规划项`; the
adapter never substitutes a target ID, field path, subject key, or progress
value. Author-authored node text remains author content and is not reclassified
as an internal diagnostic merely because it resembles a technical token.

Rows are deduplicated internally by
`chapterNumber + targetType + targetId + status`; the target ID is never
rendered. They are ordered by chapter number descending and then by stable input
order. Only the most recent 10 rows are rendered. A fixed summary reports how
many additional recognized rows are omitted, so a 720-chapter project cannot
push the Planning editor behind an unbounded progress list. No visible or DOM
attribute may contain `subjectKey`, `entityId`, `fieldPath`, `contentHash`,
revision numbers, target IDs, or raw values.

### 4.3 Unrecognized progress

Unrecognized or unmatched entries are counted but never interpolated. In a
mixed recognized/unrecognized state, the panel shows:

> 另有 2 项定稿进度已同步，暂时无法生成作者摘要。

When raw entries exist but none is recognized, the panel instead shows only:

> 定稿进度已同步，暂时无法生成作者摘要。共有 2 项暂不能展示。

It does not show `已同步 0 章` and renders no progress rows. Progress rows
omitted only because of the 10-row display limit use a separate fixed summary:

> 还有 4 项较早进度未展开。

It must not show the rejected value, key, path, identifier, exception, or a
stringified representation. This is a presentation fallback, not a change to
the underlying Planning authority.

### 4.4 Panel states

- Invalid status envelope: `正文进度状态需要重新读取。`
- Unsynchronized: `正文进度正在同步，稍后重新读取。`
- No Canon revision: `尚无已定稿正文带来的规划进度。`
- Synchronized with no raw entries: `定稿事实已同步，当前没有规划项发生变化。`
- Synchronized with raw entries but no recognized entries: use the fixed
  unable-to-summarize state from section 4.3, without a zero-chapter summary.
- Synchronized with one or more recognized entries: heading `正文进度` plus
  `已同步 N 章定稿带来的规划进度。`
- Recognized rows appear below the summary; omitted-recognized and unmatched
  counts appear last.

`N` is the number of distinct positive chapter numbers across all recognized
entries before the 10-row display limit. The status envelope is valid only when
`synchronized` is boolean, both revision values are safe non-negative integers,
and `synchronized === (canonRevision === projectionRevision)`. Every other shape
uses the fixed invalid-status message and renders no progress rows.

The interface does not display Canon or Projection revision numbers. The panel
uses the existing paper, border, ink, muted, and vermilion design tokens and
remains visually secondary to the active Planning editor.

## 5. Creation Bible status presentation

`bible_confirmed` is a known non-actionable confirmation reason and always maps
to “omit”. Every reason renderer, including current-page and history-detail
renderers, filters omitted results. The locked baseline already renders
`已确认，作为项目永久基线。`

All other supported reasons keep explicit Chinese labels. The public fallback
for any unknown reason becomes the fixed text:

> 创作圣经状态需要重新读取。

The fallback must never interpolate the reason code. Duplicate visible reason
labels are removed while preserving first occurrence order.

The current-page eyebrow must not render `activeStatus` directly. It uses the
existing closed workspace mode: `first → 待建立`, `draft → 工作草稿`,
`head → 已确认`, `superseded → 历史修订`, and `archived → 只读归档`. Bible
history rows use the closed mapping `current → 当前修订` and
`superseded → 历史修订`; an unknown status becomes `状态待核对` without
echoing the input.
This slice does not change Bible permissions, state selection, history,
confirmation, or recovery commands. It does not claim that Bible basis metadata
or the complete history information architecture has been productized.

## 6. Accessibility and trustworthy presentation

- Keep one labeled read-only region with a semantic heading and list.
- Status-only states use readable text and do not rely on color.
- Do not add interactive controls or nested controls to the progress panel.
- Preserve the existing keyboard order, skip link, focus behavior, and reduced
  motion behavior.
- Unknown or malformed display data fails closed to fixed author text.
- No UUID, hash, internal field path, raw JSON, internal reason code, SQL, or
  exception text derived from the progress/status internals may appear in
  visible text, accessible names, DOM IDs, titles, or logs introduced by this
  slice. Existing author-authored Planning text is preserved.

## 7. Files and boundaries

Expected frontend changes are limited to:

- one focused application presentation helper for Planning progress;
- `ActualProgressPanel.vue`;
- the Planning workspace prop wiring;
- the Bible reason presentation helper/view; and
- focused unit, component, and browser acceptance coverage.

Backend DTOs and persistence remain unchanged. The existing technical values may
remain inside the validated in-memory response because this slice is an author
interface correction, not a new public API contract. They must not be rendered
or newly logged.

The expected-contract `GET /contract-draft` 404 observed during the audit is not
part of this slice because it is neither of the two approved author-facing
changes. It may be handled in a later reliability slice.

## 8. Verification

Implementation uses test-driven development. Focused tests must prove:

- every supported target kind and status maps to fixed Chinese copy;
- matched Planning nodes show only author-authored labels;
- missing targets, malformed values, unknown kinds/statuses, hostile keys, UUIDs,
  hashes, field paths, and nested JSON never reach rendered or accessible text;
- a shape-colliding ordinary `plot.*` fact, a mismatched progress path/value,
  non-global subject, non-null entity, or unsupported `volume`/`plot` target is
  rejected as unrecognized;
- unmatched entries produce only a count and fixed fallback;
- duplicate author titles do not merge distinct target IDs, internal duplicates
  do merge, and hierarchy labels distinguish nested nodes without exposing IDs;
- at most the newest 10 recognized rows render, while distinct-chapter and
  omitted-row counts cover the complete recognized set;
- valid synchronized, unsynchronized, malformed-envelope, empty, mixed, and
  reordered states remain deterministic;
- `bible_confirmed` is omitted in every display context, including history detail;
- current Bible mode and history-row status never render raw status values;
- unknown Bible reasons never echo their code;
- existing Bible recovery reasons still retain their intended Chinese guidance;
  and
- the progress panel remains read-only and has valid landmarks/headings.

Build and affected frontend regression gates must pass. A headed read-only
browser review against `典镇山河` must assert a 1440×900 viewport and
`visualViewport.scale === 1`, then inspect all three Planning tabs and the
Creation Bible body. It must use only GET requests and separately record console
errors, page errors, failed responses, request failures, Provider requests, and
external requests. Visible text, accessible names, and `id`, `title`, and
`data-*` attributes must contain none of the exact internal values observed in
the response. The review must not copy full Bible or manuscript content into
logs.

## 9. Completion boundary

Completion may claim only that Planning progress presentation and current/history
Creation Bible status labels are author-facing. It must not claim that the
complete Bible history, complete frontend flow, automatic stage transitions,
broader diagnostics, full content quality, or real Provider creation is
finished.
