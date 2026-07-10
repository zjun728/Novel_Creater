CREATE TABLE draft_write_batches (
  id CHAR(36) NOT NULL,
  project_id CHAR(36) NOT NULL,
  idempotency_key VARBINARY(120) NOT NULL,
  manifest_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  result_json JSON,
  created_at BIGINT NOT NULL,
  committed_at BIGINT DEFAULT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uniq_draft_write_batches_project_key (project_id, idempotency_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
