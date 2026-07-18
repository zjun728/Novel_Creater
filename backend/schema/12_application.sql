CREATE TABLE application_settings (
  singleton_id TINYINT PRIMARY KEY,
  fallback_provider_id CHAR(36) NULL,
  revision INT NOT NULL,
  updated_at BIGINT NOT NULL,
  FOREIGN KEY (fallback_provider_id) REFERENCES provider_profiles(id) ON DELETE RESTRICT,
  CHECK (singleton_id = 1),
  CHECK (revision >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

INSERT INTO application_settings
  (singleton_id, fallback_provider_id, revision, updated_at)
  VALUES (1, NULL, 0, 0)
;-- statement
