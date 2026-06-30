-- Novel Creator MySQL Schema
-- MySQL 5.7+ / utf8mb4

CREATE DATABASE IF NOT EXISTS novel_creator
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE novel_creator;

-- 1. 项目表
CREATE TABLE IF NOT EXISTS projects (
  id CHAR(36) PRIMARY KEY,
  title VARCHAR(200) NOT NULL DEFAULT '',
  genre VARCHAR(100) DEFAULT '',
  description TEXT DEFAULT NULL,
  target_words INT DEFAULT 100000,
  target_chapters INT DEFAULT 100,
  current_chapter_num INT DEFAULT 0,
  status VARCHAR(20) DEFAULT 'drafting',
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  INDEX idx_projects_status (status),
  INDEX idx_projects_updated (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. Provider 配置表
CREATE TABLE IF NOT EXISTS provider_profiles (
  id CHAR(36) PRIMARY KEY,
  name VARCHAR(200) NOT NULL DEFAULT '',
  provider_type VARCHAR(50) NOT NULL DEFAULT 'openai-compatible',
  base_url VARCHAR(500) DEFAULT '',
  api_key VARCHAR(500) DEFAULT '',
  model VARCHAR(200) DEFAULT '',
  stream TINYINT(1) DEFAULT 1,
  max_context_tokens INT DEFAULT 200000,
  max_output_tokens INT DEFAULT 4096,
  temperature DOUBLE DEFAULT 0.8,
  top_p DOUBLE DEFAULT 0.9,
  supports_json TINYINT(1) DEFAULT 1,
  supports_streaming TINYINT(1) DEFAULT 1,
  notes TEXT DEFAULT NULL,
  thinking JSON DEFAULT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  INDEX idx_providers_type (provider_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. 任务模型绑定表
CREATE TABLE IF NOT EXISTS task_model_bindings (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  writing_model_id CHAR(36) DEFAULT NULL,
  brainstorm_model_id CHAR(36) DEFAULT NULL,
  outline_model_id CHAR(36) DEFAULT NULL,
  audit_model_id CHAR(36) DEFAULT NULL,
  summary_model_id CHAR(36) DEFAULT NULL,
  extraction_model_id CHAR(36) DEFAULT NULL,
  market_model_id CHAR(36) DEFAULT NULL,
  polish_model_id CHAR(36) DEFAULT NULL,
  inherited_from_project_id CHAR(36) DEFAULT NULL,
  inherited_from_project_title VARCHAR(200) DEFAULT '',
  inherited_from_updated_at BIGINT DEFAULT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  INDEX idx_bindings_project (project_id),
  INDEX idx_bindings_updated (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. 章节表
CREATE TABLE IF NOT EXISTS chapters (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  chapter_num INT NOT NULL DEFAULT 0,
  title VARCHAR(200) DEFAULT '',
  story_block_id CHAR(36) DEFAULT NULL,
  final_version_id CHAR(36) DEFAULT NULL,
  status VARCHAR(20) DEFAULT 'drafting',
  summary TEXT DEFAULT NULL,
  word_count INT DEFAULT 0,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  INDEX idx_chapters_project (project_id),
  INDEX idx_chapters_num (project_id, chapter_num),
  INDEX idx_chapters_story_block (project_id, story_block_id),
  INDEX idx_chapters_status (project_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5. 章节版本表
CREATE TABLE IF NOT EXISTS chapter_versions (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  chapter_id CHAR(36) NOT NULL,
  chapter_num INT NOT NULL DEFAULT 0,
  title VARCHAR(200) DEFAULT '',
  content LONGTEXT DEFAULT NULL,
  version_type VARCHAR(30) DEFAULT 'ai_candidate',
  source_model_id CHAR(36) DEFAULT NULL,
  prompt_brief TEXT DEFAULT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  INDEX idx_versions_project (project_id),
  INDEX idx_versions_chapter (chapter_id),
  INDEX idx_versions_type (version_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 6. 创作种子表
CREATE TABLE IF NOT EXISTS creative_seeds (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  title VARCHAR(200) DEFAULT '',
  genre VARCHAR(100) DEFAULT '',
  logline TEXT DEFAULT NULL,
  protagonist TEXT DEFAULT NULL,
  desire TEXT DEFAULT NULL,
  core_conflict TEXT DEFAULT NULL,
  world_pressure TEXT DEFAULT NULL,
  opening_hook TEXT DEFAULT NULL,
  emotional_promise TEXT DEFAULT NULL,
  differentiation TEXT DEFAULT NULL,
  style_target TEXT DEFAULT NULL,
  source VARCHAR(20) DEFAULT 'user',
  risk_notes TEXT DEFAULT NULL,
  ending_anchor TEXT DEFAULT NULL,
  status VARCHAR(20) DEFAULT 'candidate',
  created_at BIGINT NOT NULL,
  INDEX idx_seeds_project (project_id),
  INDEX idx_seeds_status (project_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 7. 可能性池
CREATE TABLE IF NOT EXISTS possibility_cards (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  type VARCHAR(30) DEFAULT 'plot_twist',
  title VARCHAR(200) DEFAULT '',
  content TEXT DEFAULT NULL,
  source VARCHAR(20) DEFAULT 'ai',
  status VARCHAR(20) DEFAULT 'candidate',
  related_chapter INT DEFAULT NULL,
  related_characters JSON DEFAULT NULL,
  created_at BIGINT NOT NULL,
  INDEX idx_poss_project (project_id),
  INDEX idx_poss_type (project_id, type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 8. 创作圣经
CREATE TABLE IF NOT EXISTS creative_bible (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  premise TEXT DEFAULT NULL,
  target_reader VARCHAR(500) DEFAULT '',
  style_bible TEXT DEFAULT NULL,
  theme_bible TEXT DEFAULT NULL,
  world_rules TEXT DEFAULT NULL,
  writing_profile JSON DEFAULT NULL,
  forbidden_directions JSON DEFAULT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE INDEX idx_bible_project (project_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 8.1 样本来源：只记录来源元信息，不保存长段原文
CREATE TABLE IF NOT EXISTS sample_source (
  id CHAR(36) PRIMARY KEY,
  source_type VARCHAR(40) NOT NULL DEFAULT 'local_report',
  title VARCHAR(300) NOT NULL DEFAULT '',
  author VARCHAR(120) DEFAULT '',
  file_name VARCHAR(300) DEFAULT '',
  file_hash VARCHAR(120) DEFAULT '',
  source_note TEXT DEFAULT NULL,
  status VARCHAR(30) DEFAULT 'imported',
  imported_at BIGINT DEFAULT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  INDEX idx_sample_source_type (source_type),
  INDEX idx_sample_source_status (status),
  INDEX idx_sample_source_title (title)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 8.2 样本分块 / 分析窗口：只保存窗口指标和抽象分析，不保存 sourceText/rawExcerpt
CREATE TABLE IF NOT EXISTS sample_chunk (
  id CHAR(36) PRIMARY KEY,
  source_id CHAR(36) NOT NULL,
  chunk_order INT NOT NULL DEFAULT 0,
  chapter_label VARCHAR(200) DEFAULT '',
  window_role VARCHAR(80) DEFAULT 'report_card',
  abstract_notes_json JSON DEFAULT NULL,
  metrics_json JSON DEFAULT NULL,
  raw_hash VARCHAR(120) DEFAULT '',
  status VARCHAR(30) DEFAULT 'imported',
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  INDEX idx_sample_chunk_source (source_id, chunk_order),
  INDEX idx_sample_chunk_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 8.3 创作经验卡：候选、审核、拒绝、合并、归档的抽象写法卡
CREATE TABLE IF NOT EXISTS experience_card (
  id CHAR(36) PRIMARY KEY,
  source_id CHAR(36) DEFAULT NULL,
  source_card_ref VARCHAR(200) DEFAULT '',
  source_title VARCHAR(300) DEFAULT '',
  title VARCHAR(300) NOT NULL DEFAULT '',
  status VARCHAR(30) NOT NULL DEFAULT 'candidate',
  card_type VARCHAR(60) DEFAULT 'imported_sample',
  chapter_skeleton TEXT DEFAULT NULL,
  story_block_span TEXT DEFAULT NULL,
  protagonist_progression TEXT DEFAULT NULL,
  supporting_character_method TEXT DEFAULT NULL,
  emotional_dwell TEXT DEFAULT NULL,
  scene_dwell TEXT DEFAULT NULL,
  dialogue_naturalness TEXT DEFAULT NULL,
  setting_exposure TEXT DEFAULT NULL,
  answers_and_suspense TEXT DEFAULT NULL,
  anti_ai_notes TEXT DEFAULT NULL,
  genre_tags JSON DEFAULT NULL,
  avoid_patterns JSON DEFAULT NULL,
  chunk_ids JSON DEFAULT NULL,
  metrics_json JSON DEFAULT NULL,
  safety_flags JSON DEFAULT NULL,
  review_note TEXT DEFAULT NULL,
  reviewed_at BIGINT DEFAULT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  CHECK (status IN ('candidate','reviewed','rejected','merged','archived')),
  INDEX idx_experience_card_status (status),
  INDEX idx_experience_card_source (source_id),
  INDEX idx_experience_card_title (title)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 8.4 写作标准候选：由多张已审核经验卡合并，等待人工确认和入库
CREATE TABLE IF NOT EXISTS writing_standard_candidate (
  id CHAR(36) PRIMARY KEY,
  name VARCHAR(200) NOT NULL DEFAULT '',
  category VARCHAR(120) DEFAULT '样本库 / 人工审核',
  status VARCHAR(30) NOT NULL DEFAULT 'draft',
  source_card_ids JSON DEFAULT NULL,
  merged_guidance JSON DEFAULT NULL,
  audit_focus JSON DEFAULT NULL,
  safety_policy JSON DEFAULT NULL,
  review_note TEXT DEFAULT NULL,
  promoted_standard_id CHAR(36) DEFAULT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  CHECK (status IN ('draft','reviewing','approved','rejected','promoted')),
  INDEX idx_standard_candidate_status (status),
  INDEX idx_standard_candidate_promoted (promoted_standard_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 8.5 正式写作标准库：创作圣经读取这里的 active 标准，并与内置标准合并展示
CREATE TABLE IF NOT EXISTS writing_standard (
  id CHAR(36) PRIMARY KEY,
  name VARCHAR(200) NOT NULL DEFAULT '',
  category VARCHAR(120) DEFAULT '样本库 / 人工审核',
  version VARCHAR(40) DEFAULT 'v1',
  short_rule TEXT DEFAULT NULL,
  guidance_json JSON DEFAULT NULL,
  audit_focus JSON DEFAULT NULL,
  source_candidate_id CHAR(36) DEFAULT NULL,
  source_type VARCHAR(40) DEFAULT 'experience_card',
  status VARCHAR(30) DEFAULT 'active',
  no_direct_imitation TINYINT(1) DEFAULT 1,
  safety_flags JSON DEFAULT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  INDEX idx_writing_standard_status (status),
  INDEX idx_writing_standard_source_candidate (source_candidate_id),
  INDEX idx_writing_standard_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 9. 角色表
CREATE TABLE IF NOT EXISTS characters (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  name VARCHAR(100) DEFAULT '',
  role VARCHAR(30) DEFAULT 'supporting',
  appearance TEXT DEFAULT NULL,
  personality TEXT DEFAULT NULL,
  desire TEXT DEFAULT NULL,
  fear TEXT DEFAULT NULL,
  misbelief TEXT DEFAULT NULL,
  secret TEXT DEFAULT NULL,
  relationship_notes TEXT DEFAULT NULL,
  arc_stage VARCHAR(100) DEFAULT '',
  hard_state JSON DEFAULT NULL,
  soft_state JSON DEFAULT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  INDEX idx_chars_project (project_id),
  INDEX idx_chars_role (project_id, role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 10. 伏笔表
CREATE TABLE IF NOT EXISTS plot_threads (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  title VARCHAR(200) DEFAULT '',
  content TEXT DEFAULT NULL,
  status VARCHAR(20) DEFAULT 'candidate',
  planted_chapter INT DEFAULT NULL,
  related_characters JSON DEFAULT NULL,
  possible_resolve_window JSON DEFAULT NULL,
  resolve_options JSON DEFAULT NULL,
  resolved_chapter INT DEFAULT NULL,
  notes TEXT DEFAULT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  INDEX idx_threads_project (project_id),
  INDEX idx_threads_status (project_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 11. 滚动大纲
CREATE TABLE IF NOT EXISTS rolling_outlines (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  far_vision JSON DEFAULT NULL,
  current_volume JSON DEFAULT NULL,
  near_chapters JSON DEFAULT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE INDEX idx_outline_project (project_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 11.1 分卷 / 阶段规划
CREATE TABLE IF NOT EXISTS project_volumes (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  volume_num INT NOT NULL DEFAULT 1,
  title VARCHAR(200) DEFAULT '',
  start_chapter INT NOT NULL DEFAULT 1,
  end_chapter INT NOT NULL DEFAULT 1,
  target_words INT DEFAULT 0,
  core_goal TEXT DEFAULT NULL,
  main_conflict TEXT DEFAULT NULL,
  key_characters JSON DEFAULT NULL,
  summary TEXT DEFAULT NULL,
  foreshadowing_plan JSON DEFAULT NULL,
  unresolved_items JSON DEFAULT NULL,
  handoff_point TEXT DEFAULT NULL,
  stage_summary_report JSON DEFAULT NULL,
  summary_updated_at BIGINT DEFAULT NULL,
  audit_report JSON DEFAULT NULL,
  audit_updated_at BIGINT DEFAULT NULL,
  status VARCHAR(30) DEFAULT 'planned',
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  INDEX idx_project_volumes_project (project_id),
  INDEX idx_project_volumes_num (project_id, volume_num),
  INDEX idx_project_volumes_range (project_id, start_chapter, end_chapter),
  INDEX idx_project_volumes_status (project_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 11.2 项目级审稿报告
CREATE TABLE IF NOT EXISTS project_audit_reports (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  report_type VARCHAR(40) NOT NULL DEFAULT 'global',
  title VARCHAR(200) DEFAULT '',
  report_json JSON DEFAULT NULL,
  created_at BIGINT NOT NULL,
  INDEX idx_project_audits_project (project_id, created_at),
  INDEX idx_project_audits_type (project_id, report_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 11.3 审稿纠偏任务
CREATE TABLE IF NOT EXISTS correction_tasks (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  source_type VARCHAR(40) NOT NULL DEFAULT 'global_audit',
  source_id CHAR(36) DEFAULT NULL,
  target_module VARCHAR(40) DEFAULT 'general',
  title VARCHAR(300) NOT NULL DEFAULT '',
  description TEXT DEFAULT NULL,
  severity VARCHAR(30) DEFAULT 'minor',
  issue_type VARCHAR(50) DEFAULT 'general',
  chapter_refs JSON DEFAULT NULL,
  related_items JSON DEFAULT NULL,
  suggested_action TEXT DEFAULT NULL,
  status VARCHAR(30) DEFAULT 'pending',
  metadata JSON DEFAULT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  INDEX idx_correction_tasks_project (project_id, status),
  INDEX idx_correction_tasks_source (project_id, source_type, source_id),
  INDEX idx_correction_tasks_module (project_id, target_module)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 12. Canon 事实表
CREATE TABLE IF NOT EXISTS canon_facts (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  chapter_num INT NOT NULL DEFAULT 0,
  fact_type VARCHAR(30) DEFAULT 'plot',
  content TEXT DEFAULT NULL,
  related_characters JSON DEFAULT NULL,
  related_plot_threads JSON DEFAULT NULL,
  evidence TEXT DEFAULT NULL,
  confidence DOUBLE DEFAULT 0.8,
  status VARCHAR(20) DEFAULT 'pending_review',
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  INDEX idx_facts_project (project_id),
  INDEX idx_facts_status (project_id, status),
  INDEX idx_facts_type (project_id, fact_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 13. 临时草稿表
CREATE TABLE IF NOT EXISTS temp_drafts (
  id VARCHAR(100) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  chapter_num INT NOT NULL DEFAULT 0,
  content LONGTEXT DEFAULT NULL,
  saved_at BIGINT NOT NULL,
  INDEX idx_drafts_project (project_id),
  INDEX idx_drafts_chapter (project_id, chapter_num)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 13.1 章节小纲表
CREATE TABLE IF NOT EXISTS chapter_beat_plans (
  id VARCHAR(80) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  chapter_num INT NOT NULL DEFAULT 0,
  story_block_id CHAR(36) DEFAULT NULL,
  block_stage_id VARCHAR(80) DEFAULT NULL,
  block_stage_snapshot JSON DEFAULT NULL,
  beat_plan_source VARCHAR(64) DEFAULT NULL,
  derived_from_story_block TINYINT(1) DEFAULT 0,
  derived_reason TEXT DEFAULT NULL,
  content MEDIUMTEXT DEFAULT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE KEY uniq_chapter_beat_plan (project_id, chapter_num),
  INDEX idx_chapter_beat_plans_project (project_id, chapter_num),
  INDEX idx_chapter_beat_plans_story_block (project_id, story_block_id),
  INDEX idx_chapter_beat_plans_stage (project_id, story_block_id, block_stage_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 13.2 故事块：分卷规划和章节小纲之间的滚动剧情单元
CREATE TABLE IF NOT EXISTS story_blocks (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  volume_id CHAR(36) DEFAULT NULL,
  block_num INT NOT NULL DEFAULT 1,
  status VARCHAR(30) DEFAULT 'active',
  title VARCHAR(200) DEFAULT '',
  goal TEXT DEFAULT NULL,
  story_function VARCHAR(120) DEFAULT '',
  entry_state TEXT DEFAULT NULL,
  exit_target TEXT DEFAULT NULL,
  main_pressure TEXT DEFAULT NULL,
  key_characters JSON DEFAULT NULL,
  stage_plan JSON DEFAULT NULL,
  completed_stages JSON DEFAULT NULL,
  next_stage_suggestion TEXT DEFAULT NULL,
  unresolved_questions JSON DEFAULT NULL,
  dont_advance_yet JSON DEFAULT NULL,
  carry_over_to_next_chapter JSON DEFAULT NULL,
  capacity_assessment VARCHAR(40) DEFAULT 'normal',
  chapter_refs JSON DEFAULT NULL,
  lock_state JSON DEFAULT NULL,
  review_history JSON DEFAULT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  CHECK (status IN ('active','completed','paused','closed')),
  INDEX idx_story_blocks_project (project_id, block_num),
  INDEX idx_story_blocks_status (project_id, status),
  INDEX idx_story_blocks_volume (project_id, volume_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 13.3 故事块回看记录
CREATE TABLE IF NOT EXISTS story_block_reviews (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  story_block_id CHAR(36) NOT NULL,
  chapter_num INT DEFAULT NULL,
  decision VARCHAR(60) NOT NULL DEFAULT 'continue_current_block',
  review_json JSON DEFAULT NULL,
  created_at BIGINT NOT NULL,
  CHECK (decision IN ('continue_current_block','adjust_remaining_stages','split_unfinalized_content','complete_current_block','open_new_block')),
  INDEX idx_story_block_reviews_project (project_id, story_block_id, created_at),
  INDEX idx_story_block_reviews_decision (project_id, decision)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 14. 选题雷达（预留给 v0.4）
CREATE TABLE IF NOT EXISTS market_items (
  id CHAR(36) PRIMARY KEY,
  platform VARCHAR(50) DEFAULT '',
  category VARCHAR(100) DEFAULT '',
  title VARCHAR(300) DEFAULT '',
  author VARCHAR(100) DEFAULT '',
  tags JSON DEFAULT NULL,
  rank_name VARCHAR(100) DEFAULT '',
  rank_position INT DEFAULT 0,
  intro TEXT DEFAULT NULL,
  word_count INT DEFAULT 0,
  status VARCHAR(30) DEFAULT 'unknown',
  heat_text VARCHAR(300) DEFAULT '',
  url VARCHAR(500) DEFAULT '',
  captured_at BIGINT NOT NULL,
  ai_summary TEXT DEFAULT NULL,
  extracted_hooks JSON DEFAULT NULL,
  extracted_appeals JSON DEFAULT NULL,
  plagiarism_risk_notes TEXT DEFAULT NULL,
  project_id CHAR(36) DEFAULT NULL,
  INDEX idx_market_platform (platform),
  INDEX idx_market_category (category),
  INDEX idx_market_project (project_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 14.1 选题雷达 AI 顾问对话记录
CREATE TABLE IF NOT EXISTS market_chat_messages (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  role VARCHAR(20) NOT NULL DEFAULT 'user',
  content MEDIUMTEXT DEFAULT NULL,
  metadata JSON DEFAULT NULL,
  created_at BIGINT NOT NULL,
  INDEX idx_market_chat_project (project_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 14.2 选题雷达方向建议报告
CREATE TABLE IF NOT EXISTS market_direction_reports (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  keywords VARCHAR(200) DEFAULT '',
  content_json JSON DEFAULT NULL,
  created_at BIGINT NOT NULL,
  INDEX idx_market_direction_project (project_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 15. 设定库实体：人物 / 势力 / 地点 / 体系 / 功法 / 物品
CREATE TABLE IF NOT EXISTS setting_entities (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  entity_type VARCHAR(40) NOT NULL DEFAULT 'character',
  name VARCHAR(200) NOT NULL DEFAULT '',
  category VARCHAR(100) DEFAULT '',
  summary TEXT DEFAULT NULL,
  status VARCHAR(30) DEFAULT 'active',
  importance INT DEFAULT 3,
  aliases JSON DEFAULT NULL,
  tags JSON DEFAULT NULL,
  profile JSON DEFAULT NULL,
  first_chapter INT DEFAULT NULL,
  last_chapter INT DEFAULT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  INDEX idx_setting_entities_project (project_id),
  INDEX idx_setting_entities_type (project_id, entity_type),
  INDEX idx_setting_entities_name (project_id, name),
  INDEX idx_setting_entities_status (project_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 16. 设定库关系
CREATE TABLE IF NOT EXISTS setting_relations (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  source_entity_id CHAR(36) NOT NULL,
  target_entity_id CHAR(36) NOT NULL,
  relation_type VARCHAR(80) DEFAULT '',
  stance VARCHAR(40) DEFAULT '',
  summary TEXT DEFAULT NULL,
  is_hidden TINYINT(1) DEFAULT 0,
  evidence TEXT DEFAULT NULL,
  chapter_num INT DEFAULT NULL,
  status VARCHAR(30) DEFAULT 'active',
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  INDEX idx_setting_relations_project (project_id),
  INDEX idx_setting_relations_source (project_id, source_entity_id),
  INDEX idx_setting_relations_target (project_id, target_entity_id),
  INDEX idx_setting_relations_status (project_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 17. 设定状态变更日志
CREATE TABLE IF NOT EXISTS setting_change_events (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  entity_type VARCHAR(40) DEFAULT '',
  entity_id CHAR(36) DEFAULT NULL,
  entity_name VARCHAR(200) DEFAULT '',
  change_type VARCHAR(80) DEFAULT 'update',
  field_path VARCHAR(200) DEFAULT '',
  old_value TEXT DEFAULT NULL,
  new_value TEXT DEFAULT NULL,
  chapter_num INT DEFAULT NULL,
  evidence TEXT DEFAULT NULL,
  confidence DOUBLE DEFAULT 0.8,
  status VARCHAR(30) DEFAULT 'pending_review',
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  INDEX idx_setting_changes_project (project_id),
  INDEX idx_setting_changes_entity (project_id, entity_id),
  INDEX idx_setting_changes_status (project_id, status),
  INDEX idx_setting_changes_chapter (project_id, chapter_num)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
