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
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  INDEX idx_bindings_project (project_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. 章节表
CREATE TABLE IF NOT EXISTS chapters (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  chapter_num INT NOT NULL DEFAULT 0,
  title VARCHAR(200) DEFAULT '',
  final_version_id CHAR(36) DEFAULT NULL,
  status VARCHAR(20) DEFAULT 'drafting',
  summary TEXT DEFAULT NULL,
  word_count INT DEFAULT 0,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  INDEX idx_chapters_project (project_id),
  INDEX idx_chapters_num (project_id, chapter_num),
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
  emotional_promise VARCHAR(200) DEFAULT '',
  differentiation TEXT DEFAULT NULL,
  style_target VARCHAR(200) DEFAULT '',
  source VARCHAR(20) DEFAULT 'user',
  risk_notes TEXT DEFAULT NULL,
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
  confirmed_settings JSON DEFAULT NULL,
  forbidden_directions JSON DEFAULT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE INDEX idx_bible_project (project_id)
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
