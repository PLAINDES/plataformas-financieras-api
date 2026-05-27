# app/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from playwright.async_api import async_playwright, Browser
from contextlib import asynccontextmanager
from .core.config import settings
from .api.auth.router import router as auth_router
from .api.cms.router import router as cms_router
from .api.main.router import router as main_router
from .api.main.master_templates.router import router as master_templates_router
from .api.storage.onedrive_router import router as onedrive_router
from .api.main.calculations.router import router as calculations_router
from .api.main.chatbot.router import router as chatbot_router
from .api.main.reports.router import router as reports_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"Starting {settings.PROJECT_NAME} v{settings.VERSION}")
    print(f"API Docs: http://localhost:8000{settings.API_V1_PREFIX}/docs")

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu"
        ]
    )

    app.state.playwright = playwright
    app.state.browser = browser

    yield

    print(f"Shutting down {settings.PROJECT_NAME}")
    if hasattr(app.state, "browser") and app.state.browser:
        await app.state.browser.close()
    if hasattr(app.state, "playwright") and app.state.playwright:
        await app.state.playwright.stop()


print("--- EL SERVIDOR ESTÁ ARRANCANDO ---")
# Crear instancia de FastAPI
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    docs_url=f"{settings.API_V1_PREFIX}/docs",
    redoc_url=f"{settings.API_V1_PREFIX}/redoc",
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": settings.VERSION,
        "project": settings.PROJECT_NAME
    }


# Root endpoint
@app.get("/")
async def root():
    return {
        "message": f"Welcome to {settings.PROJECT_NAME} API",
        "version": settings.VERSION,
        "docs": f"{settings.API_V1_PREFIX}/docs"
    }


# Include routers
app.include_router(auth_router, prefix=settings.API_V1_PREFIX)
app.include_router(cms_router, prefix=settings.API_V1_PREFIX)
app.include_router(main_router, prefix=settings.API_V1_PREFIX)
app.include_router(master_templates_router, prefix=settings.API_V1_PREFIX)
app.include_router(onedrive_router, prefix=settings.API_V1_PREFIX)
app.include_router(calculations_router, prefix=settings.API_V1_PREFIX)
app.include_router(chatbot_router, prefix=settings.API_V1_PREFIX)
app.include_router(reports_router, prefix=settings.API_V1_PREFIX)

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(_, exc):
    return JSONResponse(
        status_code=500,
        content={
            "message": "Internal server error",
            "detail": str(exc) if settings.DEBUG else "An error occurred"
        }
    )


# Startup event
@app.on_event("startup")
async def startup_event():
    print(f"🚀 Starting {settings.PROJECT_NAME} v{settings.VERSION}")
    print(f"📖 API Docs: http://localhost:8000{settings.API_V1_PREFIX}/docs")


# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    print(f"👋 Shutting down {settings.PROJECT_NAME}")
