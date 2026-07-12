# M2 创作契约与创作资产设计

- 日期：2026-07-11
- 状态：用户已于 2026-07-11 整体批准，进入实施计划阶段
- 所属总体设计：`2026-07-11-writer-core-v1-design.md`
- 实施分支：`codex/writer-core-v1`
- 前置里程碑：M1 写作内核地基
- 目标 Schema：`writer-core-v1.1.0`
- 首个验收项目：`永乐大典 / 典镇山河`
- 指定真实模型：`联通云 / deepseek-v4-flash`

## 1. 目标

M2 把“一个已选定的小说种子”转化为作者确认、系统可执行且可追溯的本书创作契约，并建立可跨项目复用的个人创作资产库。

正式主流程为：

`选定种子 -> 自动生成或手动提交三个故事发动机 -> 作者比较并选择一个 -> 系统推荐三个风格 -> 作者选择主风格与可选次风格 -> 选择经验卡和允许使用的本机语料 -> 预览并确认 CreationContract/StyleContract -> 等待 M3 滚动规划`

M2 必须在真实产品页面内完成，不建立平行测试页面。真实模型只负责生成三个故事发动机；风格推荐、经验推荐和契约组装由后端确定性服务完成。

M2 的最终成果是一个不可变、可追溯、可创建新修订的创作契约。它为后续圣经、实体、人物弧光、分卷方向、故事块和章节创作提供统一输入，但本里程碑不提前创建这些实体。

## 2. 产品边界

### 2.1 M2 包含

- 项目种子池的新增、编辑、删除、选择与锁定规则。
- 三个故事发动机的真实 Provider 生成路径和等价的手动录入路径。
- 故事发动机比较、选择与批次审计。
- 全局个人风格库、经验库和本机语料索引。
- 主风格、可选次风格、偏好和反偏好的选择。
- 项目级可恢复契约草稿、预览、原子确认和修订历史。
- 八类 AI 任务的不可变模型绑定版本。
- 正式 ProjectView 五步创建向导和简化的创作资产设置入口。
- Disposable MySQL、真实浏览器和一次显式真实 Provider 验收。

### 2.2 M2 不包含

- 选题市场、全网榜单抓取、AI 选题问答和趋势预测。
- Bible、Canon、人物实体、人物弧光、分卷、故事块、SceneTask、章节、草稿或定稿数据。
- 正文生成、正文质量验收、防复制定稿门禁或 30 章样板验收。
- 风格/经验资产的审核、上架、运营、权限或 marketplace。
- 多用户、登录、权限和公网访问。
- 旧表、旧字段、旧 API、旧数据库状态或旧契约的兼容与迁移。
- 用 fake Provider、旧 artifact 或旧 runner 授予 Live、DB 或 Product Ready。

## 3. 核心原则

1. 种子选择关系是项目当前种子的唯一事实源，不在种子记录上重复维护 `selected` 状态。
2. 已确认契约只追加修订，不原地覆盖；新修订只影响后续创作。
3. 全局创作资产属于本机个人安装，不按项目重复复制；项目固定引用具体修订和内容哈希。
4. Provider 密钥、真实 base URL、本机绝对路径和小说全文不得出现在浏览器、普通 API、日志或导出中。
5. Provider 未明确返回成功时不得猜测结果、自动重试或静默切换模型。
6. 契约确认必须是单事务；依赖发生变化时完整拒绝，不产生半完成状态。
7. M2 直接重建不合理的 M1 占位表，不编写兼容层或数据迁移。
8. 正式测试必须走真实产品入口，测试代码不得成为第二套产品编排。

## 4. 正式用户流程

`CreationContractWizard` 嵌入正式 `ProjectView`，包含五步。

### 4.1 第一步：选择种子

- 展示当前项目的种子池。
- 允许新增、编辑和删除未被正式依赖的种子。存在 selected relation、发动机批次、当前契约草稿或正式契约修订中的任一依赖时不得物理删除，只能归档。
- 项目可以拥有任意数量种子，但只能选定一个。
- 首个 FinalChapter 出现后选定种子永久锁定；M2 尚无 FinalChapter，但数据约束必须预留这一领域规则。
- 进入下一步时冻结种子修订及内容哈希，后续发动机批次不得读取漂移后的种子内容。

### 4.2 第二步：比较故事发动机

作者二选一：

- 通过项目“种子/创意”任务绑定调用真实 Provider，一次生成恰好三个可比较的方案。
- 手动提交恰好三个满足相同结构的完整方案。

页面并列展示三个方案及差异，作者必须选择一个才能继续。生成失败不提供隐藏的静态方案，不自动改用其他模型。

### 4.3 第三步：选择风格

- 系统依据种子和已选故事发动机确定性推荐三个风格模板。
- 每个推荐项展示阅读体验、适用范围、同一标准场景示例和完整应用示例。
- 作者选择一个主风格，可选一个不同的次风格。
- 次风格只能补充局部风味，不得覆盖主风格的叙事距离、语言底色和整体阅读体验。
- 作者可以记录喜欢的表现和不喜欢的表现，形成项目专属 StyleContract。

### 4.4 第四步：选择经验与语料范围

- 展示系统推荐的经验卡，作者可以增删。
- 展示本机已导入语料的名称、状态和章节数量。
- 作者选择本项目允许使用的语料来源，或接受系统确定性推荐。
- M2 只确定允许范围，不选择实际参考片段；实际片段检索和使用记录属于 M5。
- 来源标题和哈希只用于资产展示、审计与追溯，不得作为故事发动机或后续正文生成 Prompt 的内容。
- 契约允许暂时不选择任何语料来源，避免语料库尚未准备好时阻断创作；但 M2 产品能力验收必须至少导入并核验一份由作者明确授权的真实 `.txt`，不能只用合成 fixture 证明本机语料链路。

### 4.5 第五步：预览并确认

预览至少包含：

- 渠道、题材、选定种子及其修订/哈希。
- 内容质量宪章/Profile 的固定版本；只展示故事质量原则摘要，不把完整审稿 Rubric 变成生成规则。
- 选定故事发动机和来源批次。
- 全书预计字数范围和章节容量策略。
- 主次风格、偏好和反偏好。
- 经验卡和允许使用的语料来源。
- 八类任务的完整模型绑定快照。
- CreationContract/StyleContract 预期修订号和内容哈希。

确认成功后页面展示“创作契约已确认，等待滚动规划”。Writer 入口保持禁用，不用占位数据伪装后续能力已经完成。

## 5. 数据模型与 Schema 重建

Schema 版本从 `writer-core-v1.0.0` 提升为 `writer-core-v1.1.0`。现有 M1 契约和资产占位表不满足 M2 约束，实施时直接删除重建。

### 5.1 种子唯一选择

- `creative_seeds`：只保存种子稳定身份、所属项目和 `candidate|archived` 生命周期，不保存可变正文，也不保存 `selected`。
- `creative_seed_revisions`：每次新增或编辑产生一条不可变内容修订，保存规范化内容和内容哈希。
- `creative_seed_heads`：保存每个 seed 的当前 revision 指针；创建顺序为 seed identity -> revision -> head，避免 MySQL 循环外键。
- `project_selected_seeds`：保存 `project_id`、`seed_id`、`seed_revision_id`、`seed_hash`、选择时间和选择版本。
- `project_id` 唯一，保证一个项目只有一个当前种子。
- 使用项目与种子的复合外键，禁止跨项目选种子。
- 更新选择时使用版本条件，防止两个页面并发覆盖。
- 编辑当前已选种子时，创建新 seed revision 并原子推进 selected relation 的修订和选择版本；旧发动机批次及正式契约继续保留，但不再满足项目 readiness。
- 项目契约就绪是确定性判断：当前 selected seed revision/hash 必须等于当前 CreationContract 冻结的 seed revision/hash。不一致时页面显示“种子已变更，需要创建新契约修订”，M3 及后续 AI 操作全部阻止，直到新契约确认。

### 5.2 故事发动机

- `story_engine_batches`：保存项目、冻结种子、绑定修订、模型标识、脱敏后的规范化请求快照、请求哈希、幂等键、状态、原始返回、公开错误和时间信息。
- `story_engine_options`：每个成功批次必须恰好三条，保存结构化方案、内容哈希和稳定顺序。
- 数据库保证成功批次恰好三条且内容哈希不同；领域服务再按故事承诺、冲突循环、主角代价、群像结构、长期变化机制和终局锚点等结构化维度检查差异。语义是否真正具有创作价值由 L4/L5 人工比较确认，不能声称数据库能够理解语义。
- 已选方案通过稳定 option ID 和内容哈希进入契约，不复制一个可漂移的当前对象。

故事发动机至少包含：

- 故事承诺与目标读者期待。
- 主角欲望、持续压力和成长方向。
- 可长期循环并持续变化的核心冲突。
- 群像结构及关键角色的独立目的。
- 能力、资源或穿越优势及其代价。
- 阶段性爽点/满足感来源。
- 长篇变化机制和避免重复升级的方法。
- 终局锚点。
- 主要风险与该方案相对另外两案的差异。

### 5.3 契约草稿与不可变修订

- `project_contract_drafts`：每个项目至多一个当前未确认草稿；允许向导保存、刷新恢复和继续编辑。确认成功后删除该可变草稿，正式历史只保存在不可变契约修订中；创建下一版时再从当前 head 克隆新的草稿。
- `creation_contracts`：不可变 CreationContract 修订，包含规范化内容和内容哈希。
- `style_contracts`：与 CreationContract 修订一一对应的不可变风格契约。
- `project_contract_heads`：保存项目当前正式契约修订和版本，使用 compare-and-swap 更新。
- 新建修订时从当前正式契约克隆为草稿；确认后追加新记录并原子移动 head。
- 历史修订永不随资产更新或绑定修改而漂移。
- 每个项目在创建或产品库重建时都初始化一条 `project_contract_heads` revision 0 记录，两个正式 contract ID 为空。首次确认以 `expectedHeadRevision=0` 做 CAS 更新到 revision 1，两个并发首次确认只能有一个成功。
- `contract_confirmation_requests` 独立保存项目、幂等键、请求哈希、结果契约 ID/修订和状态，并对 `(project_id, idempotency_key)` 建唯一约束；它承担重复确认回放，不依赖已删除的可变草稿。

### 5.4 专用资产引用

不使用只有 `asset_type + asset_id` 的松散多态表。分别建立：

- CreationContract 到选定故事发动机的引用。
- StyleContract 到主/次 StyleTemplate 修订的引用。
- CreationContract 到 ExperienceCard 修订的引用。
- CreationContract 到允许使用的 CorpusSource 修订的引用。

每条引用保存目标 ID、修订号、内容哈希和角色；数据库外键与确认服务共同验证一致性。

### 5.5 模型绑定

- 八个稳定 task key 为 `seed`、`planning`、`writing`、`audit`、`summary`、`extraction`、`polish`、`market`。
- M2 只实际调用 `seed`；`market` 等其余绑定作为项目完整配置快照保留，不代表 M2 恢复选题市场或实现对应业务。
- 模型绑定以项目为单位形成不可变整组修订。
- `project_model_binding_heads` 指向当前绑定修订。
- 八类任务必须一次完整写入、一次完整校验和一次原子切换，不允许半套更新。
- 即使当前没有启用模型，项目仍可创建完整的八行 binding revision；未解析到模型的 item 使用 `resolution_status='unbound'`，`provider_id` 和展示快照为空。
- `bindingComplete` 只表示八个 task key 齐全；某项 `bindingReady` 还要求 item 为 bound、Provider 未删除且启用，并且密钥/base URL/model 配置完整。AI 操作检查本次 task，契约确认则要求八项全部 ready。
- 契约确认固定引用绑定修订和整组内容哈希。
- 新项目默认复制最近项目的完整绑定；缺失或不可用任务回退到稳定排序的第一个启用模型；没有启用模型则阻止 AI 操作。
- Provider 删除在 M2 改为软删除：标记 `deleted`、清除密钥和连接配置、从普通列表和 fallback 候选中排除，但保留稳定 ID 及历史 binding 中已冻结的 provider/model 展示快照。历史 binding FK 因而继续 `RESTRICT`，不会因设置页删除而被改写。

### 5.6 规范 Schema Contract

所有业务 ID 使用 `CHAR(36)`，SHA-256 使用小写 `CHAR(64)`，时间使用 UTC 毫秒 `BIGINT`，规范对象使用 MySQL `JSON`。所有 revision 均为正整数，head 的未确认初始值例外为 0。外键默认 `ON DELETE RESTRICT`；历史修订不得级联删除。

核心表必须至少具有以下字段和约束：

| 表 | 必需字段 | 主键、唯一键与关键约束 |
|---|---|---|
| `creative_seeds` | `id, project_id, status, created_at, updated_at` | PK `id`；UNIQUE `(project_id,id)`；`status IN ('candidate','archived')` |
| `creative_seed_revisions` | `id, project_id, seed_id, revision, payload_json, content_hash, created_at` | PK `id`；UNIQUE `(seed_id,revision)`、`(seed_id,id)`；复合 FK `(project_id,seed_id)` |
| `creative_seed_heads` | `seed_id, revision_id, revision, content_hash, updated_at` | PK `seed_id`；复合 FK `(seed_id,revision_id)`；revision/head/hash 必须一致 |
| `project_selected_seeds` | `project_id, seed_id, seed_revision_id, seed_hash, selection_revision, selected_at, updated_at` | PK `project_id`；复合 FK `(project_id,seed_id)` 和 `(seed_id,seed_revision_id)`；`selection_revision>0` |
| `story_engine_batches` | `id, project_id, source_type, seed_id, seed_revision_id, seed_hash, binding_revision_id, binding_hash, provider_id, model_name_snapshot, idempotency_key, request_json, request_hash, status, attempt_id, attempt_started_at, lease_expires_at, raw_response_text, raw_response_hash, public_error_code, created_at, finished_at` | PK `id`；UNIQUE `(project_id,idempotency_key)`；`source_type IN ('provider','manual')`；状态闭集 `reserved|running|succeeded|failed|outcome_unknown` |
| `story_engine_options` | `id, batch_id, option_order, payload_json, content_hash, created_at` | PK `id`；UNIQUE `(batch_id,option_order)`、`(batch_id,content_hash)`；`option_order BETWEEN 1 AND 3`；batch 只有在同事务写入三条后才能转为 `succeeded` |
| `project_contract_drafts` | `project_id, id, base_head_revision, seed_revision_id, seed_hash, engine_option_id, draft_json, content_hash, draft_version, created_at, updated_at` | PK `project_id`；UNIQUE `id`；`draft_version>0`；保存时使用 draft version CAS |
| `creation_contracts` | `id, project_id, revision, seed_id, seed_revision_id, seed_hash, binding_revision_id, binding_hash, channel_profile_key, genre_profile_key, quality_charter_version, total_word_min, total_word_max, chapter_capacity_policy, reference_manifest_json, reference_manifest_hash, content_json, content_hash, confirmed_at` | PK `id`；UNIQUE `(project_id,revision)`、`(project_id,id)`；所有引用用复合 FK；总字数为正且 min ≤ max；`reference_manifest_json/hash` 是所有冻结引用的唯一快照，引用关系表是必须与其精确一致的查询投影 |
| `style_contracts` | `id, project_id, creation_contract_id, revision, merged_style_json, likes_json, dislikes_json, content_hash, confirmed_at` | PK `id`；UNIQUE `(project_id,revision)`、`creation_contract_id`、`(project_id,id)`；revision 必须与 CreationContract 相同 |
| `project_contract_heads` | `project_id, revision, creation_contract_id, style_contract_id, creation_hash, style_hash, updated_at` | PK `project_id`；revision 0 时四个 contract/hash 字段为空，revision > 0 时均非空；使用复合 FK `(project_id,contract_id)` |
| `contract_confirmation_requests` | `id, project_id, idempotency_key, request_hash, status, creation_contract_id, style_contract_id, result_revision, public_error_code, created_at, completed_at` | PK `id`；UNIQUE `(project_id,idempotency_key)`；`status IN ('reserved','succeeded','failed')`；同键异 hash 返回 409 |

专用引用表固定为：

| 表 | 必需字段和约束 |
|---|---|
| `creation_contract_engine_refs` | `creation_contract_id` PK，`engine_option_id, engine_hash`；真实 FK 到 option |
| `style_contract_template_refs` | `style_contract_id, role, style_template_id, asset_revision, asset_hash, sort_order`；PK `(style_contract_id,role)`；`role IN ('primary','secondary')`；主风格恰好一条、次风格至多一条且资产不同 |
| `creation_contract_experience_refs` | `creation_contract_id, experience_card_id, asset_revision, asset_hash, sort_order`；PK `(creation_contract_id,experience_card_id)`；UNIQUE `(creation_contract_id,sort_order)` |
| `creation_contract_corpus_refs` | `creation_contract_id, corpus_source_id, source_revision, source_hash, selection_mode, sort_order`；PK `(creation_contract_id,corpus_source_id)`；`selection_mode IN ('author','system')` |

全局资产和绑定表固定为：

| 表 | 必需字段和约束 |
|---|---|
| `style_templates` | `id, stable_key, revision, name, payload_json, provenance_json, content_hash, status, created_at`；PK `id`；UNIQUE `(stable_key,revision)`；`status IN ('active','archived')` |
| `style_template_heads` | `stable_key, style_template_id, revision, content_hash, updated_at`；PK `stable_key`；FK 指向相同 stable key 的不可变修订 |
| `experience_cards` | `id, stable_key, revision, title, category, payload_json, provenance_json, content_hash, status, created_at`；PK `id`；UNIQUE `(stable_key,revision)`；category 为批准的八类闭集 |
| `experience_card_heads` | `stable_key, experience_card_id, revision, content_hash, updated_at`；PK `stable_key`；FK 指向相同 stable key 的不可变修订 |
| `corpus_sources` | `id, source_key, revision, relative_path, title, author, source_hash, file_size, encoding, parser_version, normalizer_version, fragmenter_version, index_version, status, public_error_code, imported_at, analyzed_at`；PK `id`；UNIQUE `(source_key,revision)`、`(source_hash,parser_version,normalizer_version,fragmenter_version,index_version)`；相同字节在分析版本变化时允许形成新修订 |
| `corpus_chapters` | `id, corpus_source_id, chapter_order, title, raw_byte_start, raw_byte_end, normalized_char_start, normalized_char_end, normalized_text, content_hash, created_at`；UNIQUE `(corpus_source_id,chapter_order)` |
| `corpus_fragments` | `id, corpus_chapter_id, fragment_order, chapter_char_start, chapter_char_end, normalized_text, content_hash, index_payload, analysis_version, created_at`；UNIQUE `(corpus_chapter_id,fragment_order)` |
| `corpus_import_runs` | `id, idempotency_key, request_hash, relative_path, source_hash, status, corpus_source_id, public_error_code, parser_versions_json, created_at, completed_at`；UNIQUE `idempotency_key`；`status IN ('reserved','running','succeeded','failed')`；同键异 hash 返回 409 |
| `project_model_binding_revisions` | `id, project_id, revision, content_hash, source_project_id, created_at`；UNIQUE `(project_id,revision)`、`(project_id,id)` |
| `project_model_binding_items` | `binding_revision_id, task_key, resolution_status, provider_id, provider_name_snapshot, model_name_snapshot, item_hash`；PK `(binding_revision_id,task_key)`；task key 为八项闭集且每个 revision 恰好八条；`resolution_status IN ('bound','unbound')`；unbound 时后三个 Provider 字段为空 |
| `project_model_binding_heads` | `project_id, revision, binding_revision_id, content_hash, updated_at`；PK `project_id`；复合 FK 到所属项目的 binding revision |

现有 `provider_profiles` 在 M2 增加 `lifecycle_status IN ('active','deleted')` 和 `deleted_at`。删除命令原子写 `enabled=0`、`lifecycle_status='deleted'`、清空 `api_key/base_url` 连接配置；历史 binding item 只读取自身冻结的展示快照，永远不能借历史引用再次调用已删除 Provider。

Provider batch 的 binding/provider/model 字段必须非空；`attempt_*` 只在进入 running 时写入。Provider 原始响应明文永不落库、永不进入公开 DTO 或日志；确定收到的成功内容或严格解析失败内容只保存其原始 UTF-8 字节 SHA-256，`invalid_response` 必须携带该 hash，未取得确定内容的协议失败不伪造审计 hash。任何响应内容在解析或写入 option 前必须扫描当前连接的完整 API key/base URL（含裁剪和常见编码变体）；JSON 解码后、严格 option 构建前还必须以有深度和节点上限的迭代遍历扫描所有容器字符串，阻断 Unicode escape 或混合 escape 绕过。任一扫描命中一律按安全的 `invalid_response` 失败且不写 option。`request_json/request_hash` 只含冻结业务事实，绝不含 API key/base URL。Manual batch 的 binding/provider/model/attempt/raw-response 字段必须为空，`request_json` 保存作者提交的规范化三方案，三个 option 与 batch 在同一事务写入后直接成功。两条路径使用同一 StoryEngine JSON Schema 和差异门禁。StyleTemplate、ExperienceCard 和 CorpusSource 的 `id` 表示具体不可变修订行；stable/source key 表示跨修订身份。

### 5.7 规范 JSON Contract

JSON 在进入数据库前使用严格 Pydantic/domain model 校验，`extra='forbid'`，再以稳定 key 顺序和 UTF-8 规范序列化计算 SHA-256。数据库 JSON 类型不承担语义 Schema 校验。

- Seed `payload_json` 必需字段：`title, genre, logline, protagonist, desire, coreConflict, worldPressure, openingHook, differentiation`。
- StoryEngine `payload_json` 必需字段：`name, storyPromise, protagonistDesire, sustainedPressure, growthDirection, conflictLoop, ensembleRoles, advantageAndCost, satisfactionSources, longFormVariation, endingAnchor, risks, differentiation`。
- CreationContract `content_json` 必需字段：`schemaVersion, channelProfileKey, genreProfileKey, qualityCharterVersion, selectedSeed, selectedEngine, totalWordRange, chapterCapacityPolicy, modelBindingRevision`。这里只固定质量宪章/Profile 版本，不嵌入完整审稿 Rubric 或防 AI 检查表。
- StyleContract `merged_style_json` 必需字段：`schemaVersion, readingExperience, narrativeDistance, sentenceParagraphRhythm, dictionDensity, dialogueAndSubtext, characterVoices, emotionAndInteriority, actionExplanationEnvironment, primaryRules, secondaryFlavor, risks`；`likes_json` 和 `dislikes_json` 均为经过长度限制的字符串数组。
- StyleTemplate 和 ExperienceCard payload 使用资产 manifest 中带 `schemaVersion` 的严格 Schema；prompt-facing 字段与 provenance/source-audit 字段物理分离。

任何规范字段变更必须提升对应 `schemaVersion`，不得通过接受任意额外字段实现隐式兼容。

故事发动机的规范关系来源只允许 `creation_contract_engine_refs`；CreationContract JSON 中的 `selectedEngine` 是参与 content hash 的不可变显示快照，确认事务必须验证其 option ID/hash 与引用表一致，后续业务查询以引用表为准。

## 6. Provider Gateway 与批次状态机

M2 新建后端专用的故事发动机生成 Gateway。它复用 M1 已验证的 Provider 配置和后端密钥解析边界，但不恢复旧 `ai_proxy.py`，也不构造浏览器端或测试专用的 adapter object。

### 6.1 调用流程

1. 在短事务中读取并锁定项目、选定种子快照和当前模型绑定修订，解析 `seed` 任务的实际 Provider/model；Gateway 本身不得硬编码模型。
2. 规范化请求并计算 request hash。
3. 使用幂等键预留 `story_engine_batch`；同键同请求返回原批次，同键不同请求返回 409。
4. 提交数据库事务。
5. 在事务外调用本次冻结绑定解析出的 Provider/model。《典镇山河》L5 验收要求该解析结果必须是 `联通云 / deepseek-v4-flash`。
6. 严格解析 JSON，要求恰好三个结构完整、内容哈希不同并通过结构化差异维度门禁的方案。
7. 在新事务中写入原始结果哈希、结构化 options 和成功状态；解析或 Provider 失败则写入安全的公开失败信息。

数据库事务不得跨越网络调用。原始 Provider 内容可以受控保存在数据库用于审计，但普通 API 只返回必要的结构化方案，且所有嵌套内容都必须经过敏感信息检查。

### 6.2 调用状态与崩溃恢复

- 预留事务只写 `reserved`，不写 attempt marker。
- 真正发起网络调用前，服务生成唯一 `attempt_id`，写入 `attempt_started_at` 和短期 `lease_expires_at`，把状态改为 `running` 并先提交；一个 batch 永远只有一次 outbound attempt。
- 收到明确结果后，在新事务中从相同 attempt CAS 到 `succeeded` 或 `failed`。
- 显式 `reconcile_story_engine_batch` 命令处理进程崩溃：过期且没有 attempt marker 的 `reserved` 可安全转为 `failed/not_started`；过期 `running` 无论崩溃发生在发送前、等待中，还是 Provider 返回后但结果提交前，都只能转为 `outcome_unknown`。
- reconcile 只改变状态，不发起 Provider 调用。作者只能显式创建使用新幂等键的新批次，禁止自动重放旧 batch。
- L2 必须分别构造预留后崩溃、发送期间崩溃、收到响应后提交前崩溃，证明状态转换和零自动重试。

### 6.3 失败与重试

- 明确失败：记录可公开错误，作者显式创建新批次后重试。
- 结果未知：标记 `outcome_unknown`，不得自动重放；作者确认后显式创建新批次。
- 格式错误：保留原始结果哈希和安全诊断，不把不完整方案当作成功。
- 同一成功批次可重复读取，不重复调用 Provider。
- 禁止静默切换模型、静态 fallback、fake 结果或自动生成第四个替代方案。

### 6.4 手动路径

手动路径提交恰好三个与 Provider 方案使用相同 Schema 的完整选项，经过相同的差异性和内容校验，并形成可审计批次。手动方案不伪装成 Provider 输出。

## 7. 契约确认事务

作者点击确认时，后端在一个事务中完成：

1. 校验项目、选定种子修订和哈希未变化。
2. 校验故事发动机批次成功、选项属于该批次且哈希一致。
3. 校验主次风格、经验卡和语料来源的具体修订及哈希仍有效。
4. 校验八任务模型绑定修订完整且 head 未变化。
5. 校验当前契约 head 仍等于草稿创建时的预期版本。
6. 写入不可变 CreationContract 和 StyleContract。
7. 写入所有专用资产引用。
8. compare-and-swap 移动 `project_contract_heads`。
9. 删除已消费的可变草稿，完成确认幂等记录，并返回正式修订及哈希。

任一校验或写入失败全部回滚。重复提交通过 `contract_confirmation_requests` 中绑定项目、幂等键、请求哈希和首次结果的记录返回第一次成功结果；同键不同请求返回 409，不重复创建修订。

## 8. 全局个人创作资产

StyleTemplate、ExperienceCard 和 CorpusSource 都是本机安装级资产，不包含 `project_id`。资产通过追加新修订演进，项目契约固定引用已确认修订。

### 8.1 风格模板

M2 首批 seed manifest 必须提供恰好 8 个真正可区分的主风格模板；运行时目录和后续修订支持至少 8 个 active 模板，不把 8 写成永久上限。每个模板至少包含：

- 名称、阅读体验、适用题材和不适用情形。
- 叙事距离、句段节奏、词语密度和信息组织。
- 对话、潜台词、人物声音、情绪和内心活动策略。
- 动作、环境、说明和身体反应的使用倾向。
- 推荐写法、常见风险和反模式。
- 同一标准场景的完整对比示例。
- 至少一个能展示整体应用方式的原创完整示例。

现有 `WRITING_STYLE_STANDARDS.md` 和前端风格数据只作为编辑材料，不能原样视为已完成模板。模板需在开发过程中统一分析、编写并由用户/产品主控人工确认一次；平台不建设审核或上架流程。

### 8.2 经验卡

首批目标为 40–60 张经过人工确认、写作方法真正不同的经验卡，覆盖：

1. 情节组织。
2. 人物群像。
3. 对话和潜台词。
4. 情绪表达。
5. 内心活动。
6. 信息释放。
7. 节奏。
8. 悬念与阅读牵引。

现有 28 个原创 micro-demo 可作为候选。旧 `realCorpusExperienceCards.v3.json` 虽有 46 条来源记录，但只包含少量重复方法，不得按 46 张成品计数；必须去重、合并和重写。不得用空卡、改名副本或来源记录凑数量。

### 8.3 资产落库

使用显式、可重复、可校验的 seeding 命令写入资产。Seed manifest 保存资产稳定 ID、修订、内容哈希和包版本。相同 manifest 重跑不得产生重复资产；内容变化必须形成新修订，不覆盖已被契约引用的历史内容。

发布新修订时锁定对应 stable key，插入不可变修订，原子移动 style/experience head，并将旧修订标记 archived。运行时目录只读取 head 指向的 active 修订；人工确认时间和结论写入 manifest/provenance，不建设平台审核工作流。

## 9. 本机语料库

### 9.1 文件边界

- 初始只支持 `.txt`。
- 支持 UTF-8、UTF-8 BOM 和 GB18030。
- 对原始字节计算 SHA-256，作为来源版本证据。
- 用户配置一个 corpus root；数据库和 API 只保存/返回相对 root 的路径。
- 拒绝 `..` 穿越、绝对路径、符号链接/重解析点逃逸和扩展名伪装。
- 导入前必须修复并测试 SPA fallback 的路径 containment，避免 corpus 能力扩大静态文件读取范围。

### 9.2 数据结构

- `corpus_sources`：标题、相对路径、原始字节哈希、编码、导入状态、来源修订和版本。
- `corpus_chapters`：规范化章节文本、标题、顺序、原始/规范化偏移和文本哈希。
- `corpus_fragments`：可检索片段、章节内范围、文本哈希和生成策略版本。
- 检索索引：指向稳定 fragment ID，不复制另一套无来源文本。
- 分析记录：parser version、normalizer version、fragmenter version、analysis version、状态和安全错误。

导入必须先在临时状态完成解析、校验和索引，再原子切换为可用版本。失败时不留下半套章节或索引。

### 9.3 API 与浏览器展示

普通浏览器只展示来源名称、导入状态、章节数量、相对标识和必要的审计哈希。禁止提供整本原文下载、绝对路径或大段原文 API。受限的章节/片段读取接口只服务本机产品内的资产检查和后续检索，必须限制范围和响应大小。

M2 固定正文预览默认 600、最大 1200 个字符；片段接口默认 10、最大 20 条，每条预览最大 240 个字符，单响应预览文本总量最大 4800 个字符。请求超过硬上限返回 422，客户端不能提高服务器上限。

原始小说文件不进入 Git。M2 验收必须通过 `git ls-files` 和敏感内容扫描证明这一点。

## 10. API 设计

具体路由名可在实施计划中按现有 FastAPI 规范落定，但必须覆盖以下资源和命令。

### 10.1 项目种子

- 查询项目种子池。
- 新增、编辑、删除种子。
- 读取和更新唯一选定种子。

### 10.2 故事发动机

- 创建 Provider 生成批次。
- 查询批次状态和三个方案。
- 显式 reconcile 过期批次，只执行安全状态归类，不调用 Provider。
- 创建手动批次。
- 读取历史批次和选择结果。

### 10.3 创作资产

- 查询风格模板列表和具体修订。
- 查询经验卡及分类。
- 查询推荐风格和推荐经验卡。
- 查询可用语料来源。

### 10.4 契约

- 读取/保存项目契约草稿。
- 生成确定性预览。
- 原子确认契约。
- 读取当前 head 和修订历史。
- 从当前正式修订创建下一版草稿。

### 10.5 模型绑定与语料

- 读取八任务完整绑定和 head。
- 原子更新整组绑定。
- 有界发现配置 root 下可导入的相对 `.txt`，只返回安全相对标识、大小、预检状态和跳过原因计数。
- 导入语料并查询状态。
- 读取受限章节和片段信息。

所有错误响应只包含稳定错误码、用户可理解的信息和安全关联 ID，不返回异常对象、Provider payload、密钥、base URL 或绝对路径。

## 11. 前端状态与交互

- 正式状态通过后端 API 和现有 store/command 边界管理。
- 未确认的向导进度写入 `project_contract_drafts`，刷新和重开页面后可恢复。
- `localStorage` 只能保存纯 UI 偏好，不能成为契约或资产选择的正式来源。
- 已确认 head 默认只读；作者点击“创建新修订”后才克隆出可编辑草稿。
- 后端同时按 selected seed revision/hash 和 binding revision/hash 与当前契约冻结值计算 `contractReady`，前端只展示该结果及 reasons，不另建事实判断；种子或绑定变更后旧契约仍可查看，但必须显示失效原因并阻止进入 M3。
- 依赖缺失或模型不可用时阻止进入 Provider 步骤，并链接到设置页。
- 409 显示“项目状态已在其他页面更新”，要求重新加载，不尝试前端合并正式状态。
- `outcome_unknown` 显示未知状态和“显式创建新批次”，不自动重试。
- Settings 只新增简洁的“创作资产”和“本机语料”入口，不建设运营后台。

## 12. 安全与隐私边界

M2 延续并扩大 M1 的敏感信息不出后端原则：

- 任何 Provider 列表、详情、错误、日志和嵌套 API 结构都不得出现明文密钥。
- 前端只看到 provider/model 的展示名称、启用状态和 `hasKey` 等非敏感标识。
- Uvicorn、FastAPI 和 Gateway 异常链必须继续经过敏感信息过滤。
- 浏览器不得看到真实 Provider base URL、数据库 DSN、内部调试字段、本机 corpus root 或绝对文件路径。
- 普通 API 不导出小说全文；契约 API 只返回资产引用和必要的短示例。
- corpus path containment 和 SPA fallback containment 必须有针对性的负面测试。

当前产品仍只允许 `127.0.0.1` 本机单用户访问。M2 不扩大到局域网或公网。

## 13. 测试策略

M2 实施顺序固定为：

1. Schema 和领域约束。
2. 模型绑定和 Provider Gateway。
3. 语料、资产和显式 seeding。
4. API、store 和五步向导。
5. Disposable DB 与真实浏览器测试。
6. 明确重建本机产品 Schema。
7. 真实 UI/Provider 最终验收。

根目录新增统一入口 `npm run test:milestone2`。M1 已发布证据和原始结果保持冻结；M2 为仍需保留的 M1 行为建立适配 `writer-core-v1.1.0` 的回归测试。旧 M1 中精确断言 v1.0.0 Schema、表数量、只读路由或 M1 专用浏览器入口的测试不要求原样继续通过，也不得改写旧证据冒充 M2。

### 13.1 L1：单元和协议测试

验证规范化、哈希、严格 JSON Schema、三方案差异性、推荐、状态机、路径校验、脱敏和领域错误。fake Provider 只证明函数和协议，不能授予真实链路 Ready。

### 13.2 L2：Disposable MySQL 集成测试

使用全新临时数据库验证：

- `writer-core-v1.1.0` 从空库建立及版本拒绝规则。
- 唯一种子选择、跨项目外键和并发 CAS。
- 故事发动机幂等、同键异请求 409、未知状态和严格三方案约束。
- 契约追加修订、head CAS、资产漂移拒绝和任一步失败完整回滚。
- 八任务绑定继承、缺项回退、无启用模型阻断和整组原子更新。
- 八行 unbound 表达、`bindingComplete`/`bindingReady` 区分、Provider 软删除后历史快照不变且当前调用被阻止。
- 语料编码、哈希、章节边界、偏移、片段索引、重复导入和失败无残留。
- 路径穿越、符号链接逃逸、SPA fallback 越界和秘密泄露负面场景。

### 13.3 L3：固定真实浏览器回归

浏览器只能从正式页面操作，不得用 `page.request` 或直接 API 写入替代产品步骤。测试数据库与产品库明确分离。至少覆盖：

- 五步向导正常路径和刷新恢复。
- 返回上一步、重复点击、双页面 409、模型不可用和 Provider 结果未知。
- 手动三方案路径。
- 契约确认后的只读状态、历史修订和 Writer 禁用状态。
- 页面 DOM、网络响应、控制台和后端日志中无密钥、base URL、绝对路径和整本原文。

### 13.4 L4：探索测试与人工资产验收

产品主控使用真实浏览器进行非固定探索，主动测试乱序、刷新、快速重复操作、失败恢复和不同选择组合。

人工逐项检查首批 8 个风格模板和 40–60 张经验卡：内容完整、方法真实不同、示例可理解、没有空项、改名副本、机械重复或旧 artifact 自我认证。资产报告只能记录人工结果，不能自行证明质量。

语料能力人工验收至少导入一份明确授权的真实 `.txt`，抽查原始字节 SHA-256、编码、章节数量、章节边界和数据库回读；同时记录配置 root 中发现、导入、跳过和失败的文件数量及原因，不用硬编码“40 本”或当前机器上的偶然文件数作为产品不变量。

### 13.5 L5：真实产品 Provider 验收

由于 M2 采用包含真实 Provider 的路线，最终必须执行一次受控的真实链路：

1. 打开正式《典镇山河》ProjectView。
2. 使用已选定种子和项目正式任务绑定。
3. 页面触发 `联通云 / deepseek-v4-flash`。
4. 后端 Gateway 调用 Provider 并返回恰好三个结构完整、明显不同的方案。
5. 作者/产品主控检查三个方案的故事承诺、长篇冲突循环、人物欲望与代价、群像差异、变化空间和避免重复升级能力。
6. 页面选择一个方案，完成资产选择并确认契约。
7. 从正式页面重新加载，核对产品数据库和 UI 回读的 batch ID、契约修订和内容哈希一致。

该验收不自动重复调用 Provider，不用成本换取测试稳定性，也不证明章节正文质量。

## 14. M2 完成定义

M2 只有同时满足以下条件才能标记为 **L5 M2 Contract-Generation Ready**：

- Schema 为 `writer-core-v1.1.0`，从空库初始化和版本拒绝均通过。
- 正式产品库已明确重建，保留“永乐大典”、三个种子和 Provider 配置。
- 全局资产已通过显式 manifest 写入：8 个风格模板、40–60 张人工确认的不同经验卡。
- 原始小说文件未进入 Git，语料索引不暴露绝对路径或整本原文。
- 适配 v1.1.0 的 M1 保留行为回归和 M2 L1/L2/L3 测试全部通过，L4 人工验收有可追溯记录。
- 验收证据记录实际使用的 MySQL、Python、FastAPI、Starlette、Uvicorn、Node 和浏览器版本，避免只靠宽泛依赖下限形成不可复现结论。
- `联通云 / deepseek-v4-flash` 的一次真实产品页面验收通过。
- 《典镇山河》存在正式 CreationContract/StyleContract 修订 1，页面和数据库回读一致。
- Provider 密钥、base URL、DSN、绝对路径和调试信息未出现在 API、浏览器或日志。
- Canon 与 Projection revision 仍为 0；规划、故事块、章节、草稿和定稿保持为空。
- 分支和提交证据清楚，远端 main 未经独立发布批准不会被自动改写。

该 Ready 标签只证明创作契约生成、资产固定和真实 Provider 链路完成。它不证明滚动规划、Writer、正文生成、内容质量、定稿或完整产品 Ready。

## 15. 产品数据库最终状态

M2 最终产品数据库应当包含：

- “永乐大典”项目及三个种子，`典镇山河` 为唯一选定种子。
- 完整保留重建前当前 Provider 配置集及可用的八任务模型绑定；单独断言 `联通云 / deepseek-v4-flash` 存在并可用于《典镇山河》的 `seed` 任务，不把当前 Provider 行数写成产品不变量。
- 全局风格模板、经验卡和已明确导入的本机语料索引。
- 《典镇山河》的故事发动机成功批次、三个方案、选择结果。
- CreationContract/StyleContract 正式修订 1 及其 head、专用资产引用和哈希。

不应包含：

- M2 测试产生的临时项目、临时批次或失败夹具。
- Bible、Canon 事件、Projection 内容、人物弧光、分卷、故事块、章节、草稿和定稿。
- 旧表、旧字段、旧 API 兼容状态或 shadow QA 产物。

## 16. 实施计划入口

本规格整体批准后，下一步使用 writing-plans 流程编写可执行实施计划。计划必须把数据库重建、Provider 调用和产品库验收放在明确检查点之后；任何实际 Provider 调用和产品数据库重建都要在相应测试已通过后执行。

M2 完成并通过独立审查后，才能进入 M3：Bible、实体、人物弧光、分卷方向、StoryBlock/StoryStage/SceneTask 和滚动规划。
