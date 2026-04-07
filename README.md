# Financiera Project Documentation

## Overview

Financiera is a full-stack web application for financial management and content management. The project consists of a backend API built with FastAPI and a frontend built with React/TypeScript.

## Architecture

### Backend
- **Framework**: FastAPI (Python)
- **Database**: MySQL with SQLAlchemy ORM
- **Authentication**: JWT-based with bcrypt password hashing
- **Migration Tool**: Alembic
- **Key Dependencies**:
  - fastapi: Web framework
  - sqlalchemy: ORM
  - pymysql: MySQL driver
  - pydantic: Data validation
  - python-jose: JWT handling

### Frontend
- **Framework**: React 19 with TypeScript
- **Build Tool**: Vite
- **Styling**: TailwindCSS
- **State Management**: Zustand
- **Routing**: React Router DOM
- **Key Dependencies**:
  - react/react-dom: UI framework
  - @heroicons/react: Icons
  - react-router-dom: Routing

## Project Structure

```
backend/
├── app/
│   ├── api/          # API routes (auth, cms, kapital, valora)
│   ├── core/         # Configuration, security, permissions
│   ├── db/           # Database connection and base models
│   ├── models/       # SQLAlchemy models (user, cms)
│   ├── repositories/ # Data access layer
│   ├── schemas/      # Pydantic schemas
│   └── services/     # Business logic
├── migrations/       # Alembic migrations
└── requirements.txt  # Python dependencies

frontend/
├── src/
│   ├── app/          # Page components (admin, kapital, valora, landing)
│   ├── components/   # Reusable components
│   ├── context/      # React contexts
│   ├── hooks/        # Custom hooks
│   ├── services/     # API services
│   ├── store/        # Zustand stores
│   ├── styles/       # Global styles
│   ├── types/        # TypeScript type definitions
│   └── utils/        # Utilities and helpers
└── package.json      # Node dependencies
```

## Key Features

- User authentication and authorization
- Content Management System (CMS) for pages, content, and media
- Financial analysis modules (Kapital, Valora)
- Admin panel for content editing
- Responsive frontend with modern UI

## Extraccion de Plantillas Maestras

Este proyecto incluye un flujo dedicado para plantillas maestras (`main_master_templates`) que extrae codigos de plantilla y graficos desde archivos Excel.

### Como funciona la extraccion de codigos

El extractor revisa solo las hojas definidas por el mapeo:

- `Plantilla Usuario` -> `valora`
- `WACC` -> `kapital`

Pasos del proceso:

1. Carga el workbook desde bytes con `openpyxl`.
2. Recorre celdas en las hojas mapeadas.
3. Detecta codigos con patron `$$CODIGO$$`.
4. Normaliza cada codigo a formato consistente.
5. Lee el nombre asociado desde la celda contigua.
6. Devuelve resultados agrupados por tipo (`valora` y `kapital`).

Persistencia en BD:

- Cada codigo se guarda en `main_template_codes`.
- Se relaciona al master template por `main_template_codes_master_templates`.
- Si el codigo corresponde a grafico, se referencia su imagen por `template_code_image_id` (FK a `cms_media.id`).

### Comportamiento ante fallas parciales

El pipeline tolera fallas parciales:

- Si falta credencial S3, la extraccion de codigos no se bloquea.
- Si un chart falla al renderizar/subir, el proceso puede responder igual con codigos disponibles.
- Si OneDrive no esta configurado, el endpoint corta temprano con error controlado.

Esta separacion evita que la ruta textual (codigos) dependa de la ruta de entrega de imagenes.

### Compatibilidad de formatos xlsx

El extractor esta diseñado para ser compatible con XLSX generados por Excel, se recomienda usar Excel durante desarrollo si se planea modificar el archivo xlsx de prueba, ya que editar la plantilla maestra con otro software (LibreOffice, OnlyOffice) puede causar incompatibilidades y perdida de información.

## Technical Debt

### 1. Database Type Mismatch in CMS Auditory Logs
**Issue**: The migration for `cms_auditory_logs` table uses `mysql.BIGINT(unsigned=True)` for primary key and foreign key columns, but the SQLAlchemy model uses `BigInteger` (which defaults to signed BIGINT).

**Impact**: This creates a type inconsistency between the database schema and the ORM model. Signed vs unsigned integers have different value ranges:
- Signed BIGINT: -9,223,372,036,854,775,808 to 9,223,372,036,854,775,807
- Unsigned BIGINT: 0 to 18,446,744,073,709,551,615

**Risk**: Potential data integrity issues, especially with foreign key relationships. If the application tries to insert negative values or values exceeding the signed range, it could cause database errors.

**Recommendation**: 
- Update the model to use `BigInteger(unsigned=True)` or specify the column type explicitly
- Or modify the migration to use signed BIGINT to match the model
- Consider adding database constraints and validation in the application layer

### 2. Code Structure and Organization
**Issues**:
- Mixed use of Spanish and English in code comments and naming
- Some empty directories (kapital/, valora/ in API)
- Potential circular imports in services/repositories pattern
- Lack of comprehensive error handling and logging

### 3. Testing and Quality Assurance
**Issues**:
- No visible test files or test configuration
- No CI/CD pipeline mentioned
- Missing code coverage metrics
- No linting/formatting standards enforced

### 4. Security Considerations
**Potential Issues**:
- CORS configuration allows all origins (`allow_origins=settings.BACKEND_CORS_ORIGINS`)
- No rate limiting implemented
- Password hashing uses bcrypt but should verify implementation
- JWT tokens may lack proper expiration handling

### 5. Performance and Scalability
**Issues**:
- No caching layer implemented
- Database queries may not be optimized
- No pagination in API responses
- Static file serving not configured

## Setup Instructions

### Backend
1. Install Python 3.11+
2. `cd backend`
3. `pip install -r requirements.txt`
4. Configure environment variables in `.env`
5. `alembic upgrade head` to run migrations
6. `uvicorn app.main:app --reload`

### Frontend
1. Install Node.js 18+
2. `cd frontend`
3. `npm install`
4. `npm run dev`

## Development Notes

- Backend runs on port 8000 by default
- Frontend runs on port 5173 (Vite dev server)
- Database: MySQL (configure connection in backend/.env)
- API documentation available at `/api/v1/docs`

## Future Improvements

1. Resolve the BIGINT type mismatch
2. Add comprehensive test suite
3. Implement proper logging and monitoring
4. Add API rate limiting and security headers
5. Optimize database queries and add indexing
6. Implement caching for improved performance
7. Add internationalization support
8. Set up CI/CD pipeline