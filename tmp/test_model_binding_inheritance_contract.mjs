import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const schema = readFileSync('backend/schema.sql', 'utf8')
const database = readFileSync('backend/database.py', 'utf8')
const projectsRouter = readFileSync('backend/routers/projects.py', 'utf8')
const providersRouter = readFileSync('backend/routers/providers.py', 'utf8')
const apiClient = readFileSync('frontend/src/api/db/client.js', 'utf8')
const providerStore = readFileSync('frontend/src/stores/providerStore.js', 'utf8')
const taskBinding = readFileSync('frontend/src/components/settings/TaskModelBinding.vue', 'utf8')

const generationStores = [
  'frontend/src/stores/writerStore.js',
  'frontend/src/stores/storyBlockStore.js',
  'frontend/src/stores/volumeStore.js',
  'frontend/src/stores/novelStore.js',
  'frontend/src/stores/settingStore.js',
  'frontend/src/stores/seedStore.js',
  'frontend/src/stores/memoryStore.js',
  'frontend/src/stores/marketStore.js',
  'frontend/src/stores/compareStore.js',
  'frontend/src/stores/styleTrialStore.js'
]

assert.match(schema, /inherited_from_project_id CHAR\(36\) DEFAULT NULL/)
assert.match(schema, /inherited_from_project_title VARCHAR\(200\) DEFAULT ''/)
assert.match(schema, /inherited_from_updated_at BIGINT DEFAULT NULL/)
assert.match(schema, /idx_bindings_updated/)

assert.match(database, /ALTER TABLE task_model_bindings ADD COLUMN inherited_from_project_id/)
assert.match(database, /ALTER TABLE task_model_bindings ADD COLUMN inherited_from_project_title/)
assert.match(database, /ALTER TABLE task_model_bindings ADD COLUMN inherited_from_updated_at/)

assert.match(projectsRouter, /inherit_latest_task_model_bindings/)
assert.match(projectsRouter, /await inherit_latest_task_model_bindings\(pid/)

assert.match(providersRouter, /MODEL_BINDING_FIELDS/)
assert.match(providersRouter, /DEFAULT_TASK_PROVIDER_NAME\s*=\s*"deepseek-v4-flash"/)
assert.match(providersRouter, /DEFAULT_TASK_MODEL_NAME\s*=\s*"deepseek-v4-flash"/)
assert.match(providersRouter, /async def find_default_task_model_provider/)
assert.match(providersRouter, /async def find_latest_saved_task_model_binding/)
assert.match(providersRouter, /ORDER BY b\.updated_at DESC/)
assert.match(providersRouter, /inherited_from_project_id/)
assert.match(providersRouter, /@router\.get\("\/projects\/\{pid\}\/bindings\/status"\)/)
assert.match(providersRouter, /inheritedFromProjectTitle/)
assert.match(providersRouter, /UPDATE task_model_bindings SET/)
assert.match(providersRouter, /inherited_from_project_id=%s/)
assert.match(providersRouter, /find_default_task_model_provider\(\)/)

assert.match(apiClient, /status:\s*\(projectId\)\s*=>\s*get\(`\/projects\/\$\{projectId\}\/bindings\/status`\)/)

assert.match(providerStore, /async function resolveTaskProvider/)
assert.match(providerStore, /allowFallback/)
assert.match(providerStore, /lastModelResolution/)
assert.match(providerStore, /当前项目未配置任务模型映射/)
assert.match(providerStore, /使用兜底模型/)
assert.match(providerStore, /getBindingStatus/)

assert.match(taskBinding, /已继承上一个项目模型配置/)
assert.match(taskBinding, /当前项目未配置任务模型映射/)
assert.match(taskBinding, /inheritedFromProjectTitle/)

for (const file of generationStores) {
  const source = readFileSync(file, 'utf8')
  assert.doesNotMatch(
    source,
    /providerStore\.providers\[0\]|providers\.value\[0\]/,
    `${file} must not silently fall back to the first provider`
  )
}

console.log('model binding inheritance contract tests passed')
