CREATE TABLE review_finding_decisions (
  project_id CHAR(36) NOT NULL,
  attempt_id CHAR(36) NOT NULL,
  report_hash CHAR(64) NOT NULL,
  revision INT NOT NULL,
  ignored_finding_ids_json JSON NOT NULL,
  updated_at BIGINT NOT NULL,
  PRIMARY KEY (project_id, attempt_id),
  FOREIGN KEY (project_id, attempt_id) REFERENCES finalization_change_sets(project_id, id) ON DELETE CASCADE,
  CHECK (revision >= 1),
  CHECK (JSON_TYPE(ignored_finding_ids_json) = 'ARRAY'),
  CHECK (updated_at >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement
