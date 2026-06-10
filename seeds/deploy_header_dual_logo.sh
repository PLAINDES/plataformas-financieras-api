#!/bin/bash
# =============================================================================
# deploy_header_dual_logo.sh
# Aplica los cambios de base de datos necesarios para el header con dos logos.
#
# USO:
#   bash seeds/deploy_header_dual_logo.sh
#
# Requisitos:
#   - Docker corriendo con el contenedor "financiera-db"
#   - Usuario root con contraseña rootpassword123
# =============================================================================

set -e

DB_CONTAINER="financiera-db"
DB_NAME="financiera_db"
DB_USER="root"
DB_PASS="rootpassword123"

MYSQL="docker exec $DB_CONTAINER mysql -u$DB_USER -p$DB_PASS $DB_NAME"

echo ""
echo "========================================"
echo "  Deploy: Header Dual Logo"
echo "========================================"
echo ""

# ------------------------------------------------------------------
# 1. Asegurar que el content_type 50 (header) existe
# ------------------------------------------------------------------
echo "[1/3] Verificando content_type 'header' (id=50)..."
$MYSQL -e "
INSERT IGNORE INTO cms_content_types (id, name, label, label_plural, content_schema, icon, is_singleton, settings)
VALUES (
  50,
  'header',
  'Header',
  'Headers',
  '{\"logo\": \"string\", \"logo_right\": \"string\"}',
  'layout',
  1,
  NULL
);
"
echo "      OK"

# ------------------------------------------------------------------
# 2. Upsert del registro de contenido (id=311)
#    - Si no existe lo crea, si existe actualiza el data con ambos logos
# ------------------------------------------------------------------
echo "[2/3] Aplicando registro de contenido del header (id=311)..."
$MYSQL -e "
INSERT INTO cms_contents
  (id, page_id, content_type_id, slug, title, data, status, is_visible, created_at, updated_at)
VALUES (
  311,
  1,
  50,
  'header',
  'Configuración del Header',
  '{\"logo\": \"images/logo.png\", \"logo_right\": \"images/logo.png\"}',
  'published',
  1,
  NOW(),
  NOW()
)
ON DUPLICATE KEY UPDATE
  data       = VALUES(data),
  status     = 'published',
  is_visible = 1,
  updated_at = NOW();
"
echo "      OK"

# ------------------------------------------------------------------
# 3. Limpiar registro duplicado 312 (si existe de pruebas manuales)
# ------------------------------------------------------------------
echo "[3/3] Eliminando registro duplicado id=312 (si existe)..."
$MYSQL -e "
DELETE FROM cms_contents WHERE id = 312;
"
echo "      OK (sin efecto si no existía)"

# ------------------------------------------------------------------
# Verificación final
# ------------------------------------------------------------------
echo ""
echo "--- Verificación ---"
$MYSQL -e "SELECT id, slug, status, is_visible, data FROM cms_contents WHERE id = 311;" 2>/dev/null
echo ""
echo "========================================"
echo "  Listo. El header dual-logo está activo."
echo "========================================"
echo ""
