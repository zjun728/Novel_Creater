# Asset Library Scroll and Localization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore right-side scrolling in the product shell and display asset genre/stage values in Chinese on both canonical asset-library pages.

**Architecture:** Keep the shell's existing single internal scroll owner and repair its height chain with one root-scoped CSS rule. Add one pure presentation-label module shared by the style and experience views; API query values and persisted stable keys remain unchanged.

**Tech Stack:** Vue 3, Naive UI, CSS Grid, Node.js built-in test runner, Vue SSR tests, Vite, Playwright CLI.

---

### Task 1: Restore the product shell scroll owner

**Files:**
- Modify: `frontend/tests/unit/appFeedback.test.mjs`
- Modify: `frontend/src/style.css`

- [ ] **Step 1: Write the failing height-chain regression test**

Append this test to `frontend/tests/unit/appFeedback.test.mjs`:

```js
test('root Naive UI provider preserves the fixed-height product shell', async () => {
  const globalCss = await readFile(
    new URL('../../src/style.css', import.meta.url),
    'utf8',
  )

  assert.match(
    globalCss,
    /#app\s*>\s*\.n-config-provider\s*\{[^}]*height:\s*100%/s,
  )
})
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
node --test frontend/tests/unit/appFeedback.test.mjs
```

Expected: FAIL only in `root Naive UI provider preserves the fixed-height product shell` because `style.css` does not yet contain the root wrapper height rule.

- [ ] **Step 3: Add the minimal root-scoped CSS fix**

Insert immediately after the existing `#app` block in `frontend/src/style.css`:

```css
#app > .n-config-provider {
  height: 100%;
}
```

Do not change `overscroll-behavior`, sidebar positioning, or body scrolling. Once the height chain is restored, `.product-app-shell__content` remains the intended scroll owner.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run:

```powershell
node --test frontend/tests/unit/appFeedback.test.mjs
```

Expected: PASS with no warnings.

- [ ] **Step 5: Commit the isolated layout fix**

```powershell
git add -- frontend/tests/unit/appFeedback.test.mjs frontend/src/style.css
git commit -m "fix: restore asset library content scrolling"
```

### Task 2: Localize genre and creation-stage presentation

**Files:**
- Create: `frontend/src/utils/assetTaxonomyLabels.js`
- Modify: `frontend/tests/unit/creativeAssetViews.test.mjs`
- Modify: `frontend/src/views/assets/StyleLibraryView.vue`
- Modify: `frontend/src/views/assets/ExperienceLibraryView.vue`

- [ ] **Step 1: Write failing SSR tests for both canonical pages**

Add this shared fixture and test to `frontend/tests/unit/creativeAssetViews.test.mjs`:

```js
const allTaxonomyEligibility = {
  genres: [
    'general', 'fantasy', 'xianxia', 'wuxia', 'historical',
    'horror', 'mystery', 'romance', 'science_fiction', 'urban',
    'new_genre',
  ],
  creationStages: [
    'contract', 'planning', 'chapter_outline',
    'drafting', 'revision', 'quality_audit', 'new_stage',
  ],
}

test('asset libraries render Chinese genre and stage labels with safe fallback', async () => {
  const state = {
    inventory,
    styleTemplates: [{
      id: 'style-localized',
      stableKey: 'localized-style',
      revision: 1,
      contentHash: 'e'.repeat(64),
      name: '本地化风格',
      readingExperience: '本地化标签验证',
      applicability: ['标签验证'],
      eligibility: allTaxonomyEligibility,
    }],
    experienceCards: [{
      id: 'card-localized',
      stableKey: 'localized-card',
      revision: 1,
      contentHash: 'f'.repeat(64),
      title: '本地化经验卡',
      category: 'dialogue',
      method: '本地化标签验证',
      applicability: ['标签验证'],
      eligibility: allTaxonomyEligibility,
    }],
    loadingStyles: false,
    loadingCards: false,
    styleError: '',
    cardError: '',
    inventoryError: '',
  }
  const [styleHtml, experienceHtml] = await Promise.all([
    renderView(StyleLibraryView, state),
    renderView(ExperienceLibraryView, state),
  ])

  for (const html of [styleHtml, experienceHtml]) {
    for (const label of [
      '通用题材', '玄幻', '仙侠', '武侠', '历史',
      '恐怖', '悬疑', '言情', '科幻', '都市',
      '创作契约', '故事规划', '章节小纲',
      '正文写作', '修订', '质量审核',
    ]) assert.match(html, new RegExp(`>${label}<`))
    assert.match(html, />new_genre</)
    assert.match(html, />new_stage</)
    assert.doesNotMatch(
      html,
      />(general|fantasy|xianxia|wuxia|historical|horror|mystery|romance|science_fiction|urban|contract|planning|chapter_outline|drafting|revision|quality_audit)</,
    )
  }
})
```

- [ ] **Step 2: Run the view tests and verify RED**

Run:

```powershell
node --test frontend/tests/unit/creativeAssetViews.test.mjs
```

Expected: FAIL in the new localization test because both views still render raw English values.

- [ ] **Step 3: Create the pure shared presentation mapping**

Create `frontend/src/utils/assetTaxonomyLabels.js`:

```js
const GENRE_LABELS = Object.freeze({
  general: '通用题材',
  fantasy: '玄幻',
  xianxia: '仙侠',
  wuxia: '武侠',
  historical: '历史',
  horror: '恐怖',
  mystery: '悬疑',
  romance: '言情',
  science_fiction: '科幻',
  urban: '都市',
})

const CREATION_STAGE_LABELS = Object.freeze({
  contract: '创作契约',
  planning: '故事规划',
  chapter_outline: '章节小纲',
  drafting: '正文写作',
  revision: '修订',
  quality_audit: '质量审核',
})

function displayLabel(labels, value) {
  const stableValue = value == null ? '' : String(value)
  return labels[stableValue] || stableValue
}

export function genreLabel(value) {
  return displayLabel(GENRE_LABELS, value)
}

export function creationStageLabel(value) {
  return displayLabel(CREATION_STAGE_LABELS, value)
}
```

- [ ] **Step 4: Use the mapping in `StyleLibraryView.vue`**

Import the functions:

```js
import {
  creationStageLabel,
  genreLabel,
} from '@/utils/assetTaxonomyLabels.js'
```

Build selector options without changing their submitted values:

```js
const genreOptions = computed(() => (inventory.value.genres || []).map(value => ({
  label: genreLabel(value),
  value,
})))
const stageOptions = computed(() => (inventory.value.creationStages || []).map(value => ({
  label: creationStageLabel(value),
  value,
})))
```

Render localized typed tags with collision-safe Vue keys:

```vue
<span v-for="tag in item.eligibility?.genres || []" :key="`genre:${tag}`">{{ genreLabel(tag) }}</span>
<span v-for="tag in item.eligibility?.creationStages || []" :key="`stage:${tag}`">{{ creationStageLabel(tag) }}</span>
```

- [ ] **Step 5: Use the same mapping in `ExperienceLibraryView.vue`**

Apply the same import, selector-option mapping, and typed-tag rendering shown in Step 4. Keep the `value` fields, query construction, category labels, and status labels unchanged.

- [ ] **Step 6: Run the view tests and verify GREEN**

Run:

```powershell
node --test frontend/tests/unit/creativeAssetViews.test.mjs
```

Expected: all tests PASS with no warnings.

- [ ] **Step 7: Commit the localization change**

```powershell
git add -- frontend/src/utils/assetTaxonomyLabels.js frontend/tests/unit/creativeAssetViews.test.mjs frontend/src/views/assets/StyleLibraryView.vue frontend/src/views/assets/ExperienceLibraryView.vue
git commit -m "fix: localize asset library taxonomy labels"
```

### Task 3: Regression and real-browser verification

**Files:**
- Verify only; no production file changes expected.

- [ ] **Step 1: Run the complete frontend unit suite**

Run:

```powershell
node scripts/run-tests.mjs frontend-unit
```

Expected: all frontend unit tests PASS.

- [ ] **Step 2: Build the production frontend**

Run:

```powershell
npm run build
```

Expected: Vite completes successfully with no build errors.

- [ ] **Step 3: Verify the style library in a real browser**

With the already-running local backend and Vite frontend, open `/assets/styles` in a Playwright CLI session at a 1600×900 viewport. Record the initial `.product-app-shell__content.scrollTop`, position the mouse over a style card, issue a positive mouse wheel delta, and read `scrollTop` again.

Expected:

```text
content clientHeight < content scrollHeight
content scrollTop after wheel > content scrollTop before wheel
body scrollTop remains 0
```

Also open the genre and stage selectors and confirm their known options are Chinese.

- [ ] **Step 4: Verify the experience library in the same browser**

Navigate to `/assets/experience`, repeat the wheel check over an experience card, and inspect the genre/stage selectors and visible typed tags.

Expected: right-side scrolling works; known genre and creation-stage values are Chinese; stable keys, package versions, and category values remain unchanged.

- [ ] **Step 5: Confirm repository scope**

Run:

```powershell
git diff --check
git status --short --branch
```

Expected: no whitespace errors; only the pre-existing untracked `.review-worktrees/` remains; `main` is ahead of `origin/main` only by the approved documentation and implementation commits.
