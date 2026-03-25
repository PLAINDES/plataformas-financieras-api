-- ─── cms_media ────────────────────────────────────────────────────────────────
INSERT INTO `cms_media` (
        `id`,
        `filename`,
        `original_name`,
        `mime_type`,
        `size`,
        `url`,
        `storage_path`,
        `alt_text`,
        `caption`,
        `folder`,
        `uploaded_by`,
        `meta`,
        `created_at`,
        `updated_at`,
        `deleted_at`
    )
VALUES
  (30,
   'eeff_valora_chile_tecnologia.xlsx',
   'EEFF_Chile_Tecnologia.xlsx',
   'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
   204800,
   '/storage/eeff/eeff_valora_chile_tecnologia.xlsx',
   'public/storage/eeff/eeff_valora_chile_tecnologia.xlsx',
   'EEFF Chile Tecnología',
   'Estados financieros — proyecto Valora Chile / Tecnología',
   '/eeff', 15,
   JSON_OBJECT('sheets', 3, 'rows', 120),
   '2026-03-10 10:05:00', '2026-03-10 10:05:00', NULL),

  (31,
   'eeff_valora_peru_retail.xlsx',
   'EEFF_Peru_Retail.xlsx',
   'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
   318200,
   '/storage/eeff/eeff_valora_peru_retail.xlsx',
   'public/storage/eeff/eeff_valora_peru_retail.xlsx',
   'EEFF Perú Retail',
   'Estados financieros — proyecto Valora Perú / Retail',
   '/eeff', 15,
   JSON_OBJECT('sheets', 3, 'rows', 98),
   '2026-03-09 13:40:00', '2026-03-09 13:40:00', NULL),

  (32,
   'grafico-prima-mercado.png',
   'Grafico_Prima_Mercado.png',
   'image/png',
   87400,
   '/storage/template-codes/grafico-prima-mercado.png',
   'public/storage/template-codes/grafico-prima-mercado.png',
   'Gráfico de Prima de Mercado (Rm - Rf)',
   'Gráfico histórico prima de mercado — hoja WACC',
   '/template-codes', 15,
   JSON_OBJECT('width', 800, 'height', 400, 'format', 'png'),
   '2026-03-10 09:00:00', '2026-03-10 09:00:00', NULL),

  (33,
   'portada-kapital-wacc.png',
   'Portada_Kapital_WACC.png',
   'image/png',
   142000,
   '/storage/covers/portada-kapital-wacc.png',
   'public/storage/covers/portada-kapital-wacc.png',
   'Portada Reporte WACC Kapital',
   'Portada principal para reportes Kapital WACC',
   '/covers', 15,
   JSON_OBJECT('width', 1240, 'height', 1754, 'format', 'png'),
   '2026-03-10 09:05:00', '2026-03-10 09:05:00', NULL),

  (34,
   'footer-logo-kapital.png',
   'Footer_Logo_Kapital.png',
   'image/png',
   34200,
   '/storage/covers/footer-logo-kapital.png',
   'public/storage/covers/footer-logo-kapital.png',
   'Logo Kapital footer',
   'Logo inferior para portadas Kapital',
   '/covers', 15,
   JSON_OBJECT('width', 300, 'height', 80, 'format', 'png'),
   '2026-03-10 09:06:00', '2026-03-10 09:06:00', NULL);


-- ─── main_calculations (valora) ───────────────────────────────────────────────
INSERT INTO `main_calculations` (
        `id`,
        `calculation_file_id`,
        `user_id`,
        `code`,
        `type`,
        `data`,
        `created_at`,
        `updated_at`
    )
VALUES
  (101, 30, 15,
   SUBSTRING(SHA2('valora-chile-tecnologia-15-2026-03-10', 256), 1, 64),
   'valora',
   JSON_OBJECT(
     'pais',     'Chile',   'moneda',  'CLP',
     'sector',   'Tecnología', 'fecha', '2026-03-10',
     'archivo',  'EEFF_Chile_Tecnologia.xlsx', 'media_id', 3
   ),
   '2026-03-10 10:09:36', '2026-03-10 10:09:36'),

  (102, 31, 16,
   SUBSTRING(SHA2('valora-peru-retail-16-2026-03-09', 256), 1, 64),
   'valora',
   JSON_OBJECT(
     'pais',    'Perú',  'moneda',  'PEN',
     'sector',  'Retail', 'fecha',  '2026-03-09',
     'archivo', 'EEFF_Peru_Retail.xlsx', 'media_id', 4
   ),
   '2026-03-09 13:47:53', '2026-03-09 13:47:53'),

  (103, NULL, 14,
   SUBSTRING(SHA2('valora-colombia-energia-14-2026-03-07', 256), 1, 64),
   'valora',
   JSON_OBJECT(
     'pais',    'Colombia', 'moneda', 'COP',
     'sector',  'Energía',  'fecha',  '2026-03-07',
     'archivo', NULL
   ),
   '2026-03-07 07:33:40', '2026-03-07 07:33:40');


-- ─── main_calculations (kapital) ─────────────────────────────────────────────
INSERT INTO `main_calculations` (
        `id`,
        `calculation_file_id`,
        `user_id`,
        `code`,
        `type`,
        `data`,
        `created_at`,
        `updated_at`
    )
VALUES
  (201, NULL, 15,
   SUBSTRING(SHA2('kapital-finanzas-chile-15-2026-03-10', 256), 1, 64),
   'kapital',
   JSON_OBJECT(
     'industria','Finanzas',  'fecha','2026-03-10',
     'pais','Chile',          'moneda','USD',
     'tasa_libre_riesgo',4.5, 'anio_bono',1,
     'devaluacion',2.0,       'tasa_impositiva',27.0,
     'costo_deuda',6.2,       'porcentaje_deuda',40,
     'porcentaje_capital',60, 'dc_ratio',0.6667,
     'tasa_efectiva_impuesto',25.3,
     'beta_apalancado',1.25,  'beta_desapalancado',0.89
   ),
   '2026-03-10 11:20:00', '2026-03-10 11:20:00'),

  (202, NULL, 16,
   SUBSTRING(SHA2('kapital-mineria-peru-16-2026-03-08', 256), 1, 64),
   'kapital',
   JSON_OBJECT(
     'industria','Minería',   'fecha','2026-03-08',
     'pais','Perú',           'moneda','USD',
     'tasa_libre_riesgo',3.8, 'anio_bono',2,
     'devaluacion',3.5,       'tasa_impositiva',29.5,
     'costo_deuda',7.0,       'porcentaje_deuda',55,
     'porcentaje_capital',45, 'dc_ratio',1.2222,
     'tasa_efectiva_impuesto',28.1,
     'beta_apalancado',1.48,  'beta_desapalancado',0.95
   ),
   '2026-03-08 09:15:22', '2026-03-08 09:15:22'),

  (203, NULL, 14,
   SUBSTRING(SHA2('kapital-retail-colombia-14-2026-03-05', 256), 1, 64),
   'kapital',
   JSON_OBJECT(
     'industria','Retail',    'fecha','2026-03-05',
     'pais','Colombia',       'moneda','USD',
     'tasa_libre_riesgo',5.1, 'anio_bono',1,
     'devaluacion',4.2,       'tasa_impositiva',35.0,
     'costo_deuda',8.5,       'porcentaje_deuda',30,
     'porcentaje_capital',70, 'dc_ratio',0.4286,
     'tasa_efectiva_impuesto',32.7,
     'beta_apalancado',0.98,  'beta_desapalancado',0.81
   ),
   '2026-03-05 14:00:45', '2026-03-05 14:00:45'),

  (204, NULL, 15,
   SUBSTRING(SHA2('kapital-banca-peru-15-2026-03-12', 256), 1, 64),
   'kapital',
   JSON_OBJECT(
     'industria','Banca',     'fecha','2026-03-12',
     'pais','Perú',           'moneda','USD',
     'tasa_libre_riesgo',4.2, 'anio_bono',2,
     'devaluacion',2.8,       'tasa_impositiva',29.5,
     'costo_deuda',5.9,       'porcentaje_deuda',65,
     'porcentaje_capital',35, 'dc_ratio',1.8571,
     'tasa_efectiva_impuesto',27.4,
     'beta_apalancado',1.10,  'beta_desapalancado',0.72
   ),
   '2026-03-12 08:45:00', '2026-03-12 08:45:00');


-- ─── main_covers ─────────────────────────────────────────────────────────────
INSERT INTO `main_covers` (
        `id`,
        `nombre`,
        `tipo`,
        `portada_id`,
        `primer_imagen_footer_id`,
        `segundo_imagen_footer_id`,
        `logo_superior_id`,
        `imagen_central_id`,
        `logo_inferior_id`,
        `imagen_fondo_id`,
        `created_at`,
        `updated_at`,
        `deleted_at`
    )
VALUES
  (10,
   'Portada Kapital WACC — Finanzas',
   'imagen_adjuntada',
   32, 33, NULL,
   NULL, NULL, 34, NULL,
   '2026-03-10 09:10:00', '2026-03-10 09:10:00', NULL);


-- ─── main_templates ──────────────────────────────────────────────────────────
INSERT INTO `main_templates` (
        `id`,
        `nombre`,
        `template_file_id`,
        `is_default`,
        `created_at`,
        `updated_at`,
        `deleted_at`
    )
VALUES
  (10,
   'Template Kapital WACC — Estándar',
   NULL, 1,
   '2026-03-10 09:15:00', '2026-03-10 09:15:00', NULL);


-- ─── main_template_codes ─────────────────────────────────────────────────────
INSERT INTO `main_template_codes` (
        `id`,
        `template_code_image_id`,
        `type`,
        `hoja`,
        `nombre`,
        `code`,
        `created_at`,
        `updated_at`,
        `deleted_at`
    )
VALUES
  (10, 32,   'kapital', 'WACC', 'Gráfico de Prima de Mercado (Rm - Rf)', '$$grafico1$$', '2026-03-10 09:20:00', '2026-03-10 09:20:00', NULL),
  (11, NULL, 'kapital', 'WACC', 'Prima de Mercado (Rm - Rf)',            '$$KMZGY$$',    '2026-03-10 09:20:00', '2026-03-10 09:20:00', NULL),
  (12, NULL, 'kapital', 'WACC', 'Tasa libre de riesgo (Rf)',             '$$KMZGZ$$',    '2026-03-10 09:20:00', '2026-03-10 09:20:00', NULL),
  (13, NULL, 'kapital', 'WACC', 'Costo de Capital Financiero (Ke)',      '$$KYZA9$$',    '2026-03-10 09:20:00', '2026-03-10 09:20:00', NULL),
  (14, NULL, 'kapital', 'WACC', 'Beta Desapalancado (Boa)',              '$$TZYU$$',     '2026-03-10 09:20:00', '2026-03-10 09:20:00', NULL),
  (15, NULL, 'kapital', 'WACC', 'Prima de Riesgo País (CRP)',            '$$GH7RV$$',    '2026-03-10 09:20:00', '2026-03-10 09:20:00', NULL),
  (16, NULL, 'kapital', 'WACC', 'WACC Nominal en Moneda Local',          '$$WPBVC$$',    '2026-03-10 09:20:00', '2026-03-10 09:20:00', NULL);


-- ─── main_template_codes_main_templates ──────────────────────────────────────
INSERT INTO `main_template_codes_main_templates` (
        `template_code_id`,
        `template_id`
    )
VALUES
  (10, 10), (11, 10), (12, 10),
  (13, 10), (14, 10), (15, 10), (16, 10);

INSERT INTO `main_reports` (
        `id`,
        `template_id`,
        `file`,
        `nombre`,
        `precio`,
        `type`,
        `moneda`,
        `sector_empresa`,
        `bono_ajustado`,
        `contenido`,
        `link_pago`,
        `portada_id`,
        `activo`,
        `created_at`,
        `updated_at`,
        `deleted_at`
    )
VALUES
  (10,
   10,
   'Reporte-10.pdf',
   'Reporte WACC — Banca Perú 2026',
   1200.00,
   'kapital',
   'USD',
   'Banca',
   'Bono EE.UU. 2Y',
   'Costo de capital del sector bancario peruano',
   'https://pagos.kapital.pe/reporte/wacc-banca-2026',
   10, 1,
   '2026-03-12 09:00:00', '2026-03-12 09:00:00', NULL);