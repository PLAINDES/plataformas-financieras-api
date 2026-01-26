# app/api/__init__.py
from fastapi import APIRouter
from .auth.router import router as auth_router
from .cms.router import router as cms_router

api_router = APIRouter()

# Incluir routers
api_router.include_router(auth_router)
api_router.include_router(cms_router)