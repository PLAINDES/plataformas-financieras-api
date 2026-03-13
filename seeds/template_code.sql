INSERT INTO `cms_media` (id, filename, original_name, mime_type, size, url, storage_path, alt_text, folder, created_at, updated_at)
VALUES (
  33,
  'grafico-prima-mercado.png',
  'grafico-prima-mercado.png',
  'image/png',
  NULL,
  '/storage/template-codes/grafico-prima-mercado.png',
  'template-codes/grafico-prima-mercado.png',
  'Grafico de Prima de Mercado (Rm - Rf)',
  '/template-codes',
  NOW(),
  NOW()
);

INSERT INTO `main_templates` (id, nombre, template_file_id, is_default, created_at, updated_at)
VALUES (
  24,
  'Template Kapital WACC',
  NULL,
  1,
  NOW(),
  NOW()
);

INSERT INTO `main_template_codes` (id, template_code_image_id, type, hoja, nombre, code, created_at, updated_at)
VALUES
  (11, 33,    'kapital', 'WACC', 'Grafico de Prima de Mercado (Rm - Rf)', '$$grafico1$$', NOW(), NOW()),
  (21, NULL, 'kapital', 'WACC', 'Prima de Mercado (Rm - Rf)',            '$$KMZGY$$',    NOW(), NOW()),
  (31, NULL, 'kapital', 'WACC', 'tasa libre de riesgo (Rf)',             '$$KMZGZ$$',    NOW(), NOW());

INSERT INTO main_template_codes_main_templates
(template_code_id, template_id)
VALUES
(11,24),
(21,24),
(31,24);

INSERT INTO `main_calculations` (id, user_id, type, data, created_at, updated_at)
VALUES (
  21,
  15,
  'kapital',
  NULL,
  NOW(),
  NOW()
);

INSERT INTO `main_covers` (id, nombre, tipo, portada_id, primer_imagen_footer_id, segundo_imagen_footer_id, logo_superior_id, imagen_central_id, logo_inferior_id, imagen_fondo_id, created_at, updated_at)
VALUES (
  5,
  'Portada Kapital Principal',
  'imagen_adjuntada',
  NULL, NULL, NULL, NULL, NULL, NULL, NULL,
  NOW(),
  NOW()
);

INSERT INTO `main_reports` (id, calculation_id, code, nombre, precio, moneda, sector_empresa, bono_ajustado, contenido, link_pago, portada_id, activo, created_at, updated_at)
VALUES (
  5,
  201,
  SHA2('reporte-kapital-wacc-001', 256),
  'Reporte WACC Kapital',
  NULL,
  'SOLES',
  NULL,
  NULL,
  NULL,
  NULL,
  5,
  1,
  NOW(),
  NOW()
);