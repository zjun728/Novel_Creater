CREATE TABLE schema_metadata (
  singleton_id TINYINT PRIMARY KEY,
  schema_version VARCHAR(64) NOT NULL,
  manifest_hash CHAR(64) NOT NULL,
  initialized_at BIGINT NOT NULL,
  CHECK (singleton_id = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement
