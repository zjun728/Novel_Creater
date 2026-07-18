CREATE TABLE volume_plans (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  selection_revision INT NOT NULL,
  contract_revision INT NOT NULL,
  contract_hash CHAR(64) NOT NULL,
  bible_revision INT NOT NULL,
  bible_hash CHAR(64) NOT NULL,
  manifest_hash CHAR(64) NOT NULL,
  volume_num INT NOT NULL,
  title VARCHAR(200) NOT NULL,
  direction_json JSON NOT NULL,
  revision INT NOT NULL,
  status VARCHAR(24) NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE KEY uq_volume_num (project_id, selection_revision, contract_revision, contract_hash, bible_revision, bible_hash, volume_num),
  UNIQUE KEY uq_volume_project_id (project_id, id),
  UNIQUE KEY uq_volume_planning_identity (project_id, id, manifest_hash),
  UNIQUE KEY uq_volume_generation_identity (project_id, id, selection_revision, contract_revision, contract_hash, bible_revision, bible_hash, manifest_hash),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, selection_revision, contract_revision, contract_hash) REFERENCES creation_contracts(project_id, selection_revision, revision, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, selection_revision, contract_revision, contract_hash, bible_revision, bible_hash) REFERENCES creation_bible_revisions(project_id, selection_revision, contract_revision, contract_hash, revision, content_hash) ON DELETE RESTRICT,
  CHECK (selection_revision > 0),
  CHECK (contract_revision > 0),
  CHECK (bible_revision > 0),
  CHECK (volume_num > 0),
  CHECK (revision > 0),
  CHECK (status IN ('planned','active','completed','cancelled'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE story_blocks (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  volume_plan_id CHAR(36) NOT NULL,
  block_num INT NOT NULL,
  title VARCHAR(200) NOT NULL,
  goal_json JSON NOT NULL,
  revision INT NOT NULL,
  status VARCHAR(24) NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE KEY uq_block_num (project_id, volume_plan_id, block_num),
  UNIQUE KEY uq_block_project_id (project_id, id),
  UNIQUE KEY uq_block_planning_root (project_id, volume_plan_id, id),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, volume_plan_id) REFERENCES volume_plans(project_id, id) ON DELETE CASCADE,
  CHECK (block_num > 0),
  CHECK (revision > 0),
  CHECK (status IN ('planned','active','completed','failed','redirected'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE story_stages (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  story_block_id CHAR(36) NOT NULL,
  stage_order INT NOT NULL,
  title VARCHAR(200) NOT NULL,
  plan_json JSON NOT NULL,
  revision INT NOT NULL,
  status VARCHAR(24) NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE KEY uq_stage_order (story_block_id, stage_order),
  UNIQUE KEY uq_stage_project_id (project_id, id),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, story_block_id) REFERENCES story_blocks(project_id, id) ON DELETE CASCADE,
  CHECK (stage_order > 0),
  CHECK (revision > 0),
  CHECK (status IN ('pending','in_progress','completed','cancelled'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE scene_tasks (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  story_stage_id CHAR(36) NOT NULL,
  task_order INT NOT NULL,
  task_json JSON NOT NULL,
  revision INT NOT NULL,
  status VARCHAR(24) NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE KEY uq_scene_order (story_stage_id, task_order),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, story_stage_id) REFERENCES story_stages(project_id, id) ON DELETE CASCADE,
  CHECK (task_order > 0),
  CHECK (revision > 0),
  CHECK (status IN ('pending','in_progress','completed','cancelled'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement
