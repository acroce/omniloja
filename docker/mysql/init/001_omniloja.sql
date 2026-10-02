CREATE TABLE IF NOT EXISTS app_metadata (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  meta_key VARCHAR(120) NOT NULL,
  meta_value TEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_app_metadata_meta_key (meta_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO app_metadata (meta_key, meta_value)
VALUES ('app_name', 'omniloja')
ON DUPLICATE KEY UPDATE meta_value = VALUES(meta_value);
