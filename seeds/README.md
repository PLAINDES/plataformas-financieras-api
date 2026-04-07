# Idempotent Database Seeding

Script automático de seeding de base de datos que **no sobrescribe datos existentes** y **no genera errores** si los datos ya están presentes.

## Componentes

### 1. Scripts SQL Modificados
- `seeds/basic_data.sql` - Datos básicos del CMS (cms_content_types, cms_pages, etc.)
- `seeds/calculation_data.sql` - Datos de cálculos financieros (main_calculations, main_reports, etc.)

**Cambio clave**: Todos los `INSERT INTO` fueron reemplazados por `INSERT IGNORE INTO`

```sql
-- Antes (genera error si el ID ya existe)
INSERT INTO `cms_content_types` ...

-- Ahora (ignora silenciosamente si ya existe)
INSERT IGNORE INTO `cms_content_types` ...
```

### 2. Script de Seeding Python - Modificado
`seeds/seed_from_sql.py`

- Nueva función `table_has_data()` que verifica si una tabla ya tiene datos
- Nueva función `run_seeds_idempotent()` que ejecuta múltiples seeds de forma segura
- El script ahora puede ejecutarse en dos modos:
  - **Automático**: Sin argumentos, ejecuta todos los seeds idempotentemente
  - **Manual**: Con argumento, ejecuta un archivo SQL específico

**Lógica**:
```python
Si se llama sin argumentos:
  Para cada seed:
    1. Verifica si la tabla principal ya tiene datos
    2. Si NO tiene datos → ejecuta el SQL
    3. Si YA tiene datos → salta el seed (evita duplicados)

Si se llama con archivo como argumento:
  Ejecuta ese archivo SQL directamente
```

### 3. Entrypoint.sh Actualizado
```bash
#!/bin/bash
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Seeding database with initial data..."
python -m seeds.seed_database

echo "Starting Uvicorn server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Uso

### Automático (Docker)
El seeding se ejecuta automáticamente cuando inicia el contenedor:
```bash
docker compose up --build
```

### Manual
```bash
# Ejecutar todos los seeds (idempotente)
python -m seeds.seed_from_sql

# Ejecutar un seed específico
python -m seeds.seed_from_sql seeds/basic_data.sql
```

## Agregar Nuevos Seeds


1. **Crear archivo SQL** (`seeds/new_data.sql`):
   ```sql
   INSERT IGNORE INTO `table_name` (columns)
   VALUES (data)
   ```

2. **Registrar en `seed_from_sql.py`** (función `main`):
   ```python
   seeds = [
       (seeds_dir / 'basic_data.sql', 'cms_content_types'),
       (seeds_dir / 'calculation_data.sql', 'cms_media'),
       (seeds_dir / 'new_data.sql', 'table_to_check'),  # ← Agregar aquí
   ]
   ```

3. **Reconstruir Docker**:
   ```bash
   docker compose up --build
   ```