USE financiera_db;

CREATE TABLE IF NOT EXISTS `main_calculations` (
  `id`                    bigint unsigned NOT NULL AUTO_INCREMENT,
  `calculation_file_id`   bigint unsigned DEFAULT NULL,
  `user_id`               bigint unsigned NOT NULL,
  `type`                  enum('valora','kapital')
                            CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `data`                  json DEFAULT NULL,
  `created_at`            datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`            datetime NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_user`   (`user_id`),
  KEY `idx_type`   (`type`),
  KEY `idx_file`   (`calculation_file_id`),
  CONSTRAINT `fk_calc_user` FOREIGN KEY (`user_id`)
    REFERENCES `sys_users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_calc_media` FOREIGN KEY (`calculation_file_id`)
    REFERENCES `cms_media` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;



INSERT INTO `cms_media`
  (id, filename, original_name, mime_type, size, url, storage_path,
   alt_text, caption, folder, uploaded_by, meta, created_at, updated_at, deleted_at)
VALUES
  (3,
   'eeff_valora_chile_tecnologia.xlsx',
   'EEFF_Chile_Tecnologia.xlsx',
   'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
   204800,
   '/storage/eeff/eeff_valora_chile_tecnologia.xlsx',
   'public/storage/eeff/eeff_valora_chile_tecnologia.xlsx',
   'EEFF Chile Tecnología',
   'Estados financieros — proyecto Valora Chile / Tecnología',
   '/eeff',
   15,          
   JSON_OBJECT('sheets', 3, 'rows', 120),
   '2026-03-10 10:05:00', '2026-03-10 10:05:00', NULL),

  (4,
   'eeff_valora_peru_retail.xlsx',
   'EEFF_Peru_Retail.xlsx',
   'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
   318200,
   '/storage/eeff/eeff_valora_peru_retail.xlsx',
   'public/storage/eeff/eeff_valora_peru_retail.xlsx',
   'EEFF Perú Retail',
   'Estados financieros — proyecto Valora Perú / Retail',
   '/eeff',
   15,          
   JSON_OBJECT('sheets', 3, 'rows', 98),
   '2026-03-09 13:40:00', '2026-03-09 13:40:00', NULL);




INSERT INTO `main_calculations`
  (id, calculation_file_id, user_id, type, data, created_at, updated_at)
VALUES

  (101, 3, 15, 'valora',
   JSON_OBJECT(
     'pais',     'Chile',
     'moneda',   'CLP',
     'sector',   'Tecnología',
     'fecha',    '2026-03-10',
     'archivo',  'EEFF_Chile_Tecnologia.xlsx',
     'media_id', 3
   ),
   '2026-03-10 10:09:36', '2026-03-10 10:09:36'),

  (102, 4, 16, 'valora',
   JSON_OBJECT(
     'pais',     'Perú',
     'moneda',   'PEN',
     'sector',   'Retail',
     'fecha',    '2026-03-09',
     'archivo',  'EEFF_Peru_Retail.xlsx',
     'media_id', 4
   ),
   '2026-03-09 13:47:53', '2026-03-09 13:47:53'),

  (103, NULL, 14, 'valora',
   JSON_OBJECT(
     'pais',    'Colombia',
     'moneda',  'COP',
     'sector',  'Energía',
     'fecha',   '2026-03-07',
     'archivo', NULL
   ),
   '2026-03-07 07:33:40', '2026-03-07 07:33:40');




INSERT INTO `main_calculations`
  (id, calculation_file_id, user_id, type, data, created_at, updated_at)
VALUES

  (201, NULL, 15, 'kapital',
   JSON_OBJECT(
     'industria',              'Finanzas',
     'fecha',                  '2026-03-10',
     'pais',                   'Chile',
     'moneda',                 'USD',
     'tasa_libre_riesgo',      4.5,
     'anio_bono',              1,
     'devaluacion',            2.0,
     'tasa_impositiva',        27.0,
     'costo_deuda',            6.2,
     'porcentaje_deuda',       40,
     'porcentaje_capital',     60,
     'dc_ratio',               0.6667,
     'tasa_efectiva_impuesto', 25.3,
     'beta_apalancado',        1.25,
     'beta_desapalancado',     0.89
   ),
   '2026-03-10 11:20:00', '2026-03-10 11:20:00'),

  (202, NULL, 16, 'kapital',
   JSON_OBJECT(
     'industria',              'Minería',
     'fecha',                  '2026-03-08',
     'pais',                   'Perú',
     'moneda',                 'USD',
     'tasa_libre_riesgo',      3.8,
     'anio_bono',              2,
     'devaluacion',            3.5,
     'tasa_impositiva',        29.5,
     'costo_deuda',            7.0,
     'porcentaje_deuda',       55,
     'porcentaje_capital',     45,
     'dc_ratio',               1.2222,
     'tasa_efectiva_impuesto', 28.1,
     'beta_apalancado',        1.48,
     'beta_desapalancado',     0.95
   ),
   '2026-03-08 09:15:22', '2026-03-08 09:15:22'),

  (203, NULL, 14, 'kapital',
   JSON_OBJECT(
     'industria',              'Retail',
     'fecha',                  '2026-03-05',
     'pais',                   'Colombia',
     'moneda',                 'USD',
     'tasa_libre_riesgo',      5.1,
     'anio_bono',              1,
     'devaluacion',            4.2,
     'tasa_impositiva',        35.0,
     'costo_deuda',            8.5,
     'porcentaje_deuda',       30,
     'porcentaje_capital',     70,
     'dc_ratio',               0.4286,
     'tasa_efectiva_impuesto', 32.7,
     'beta_apalancado',        0.98,
     'beta_desapalancado',     0.81
   ),
   '2026-03-05 14:00:45', '2026-03-05 14:00:45'),

  (204, NULL, 1, 'kapital',
   JSON_OBJECT(
     'industria',              'Banca',
     'fecha',                  '2026-03-12',
     'pais',                   'Perú',
     'moneda',                 'USD',
     'tasa_libre_riesgo',      4.2,
     'anio_bono',              2,
     'devaluacion',            2.8,
     'tasa_impositiva',        29.5,
     'costo_deuda',            5.9,
     'porcentaje_deuda',       65,
     'porcentaje_capital',     35,
     'dc_ratio',               1.8571,
     'tasa_efectiva_impuesto', 27.4,
     'beta_apalancado',        1.10,
     'beta_desapalancado',     0.72
   ),
   '2026-03-12 08:45:00', '2026-03-12 08:45:00');

