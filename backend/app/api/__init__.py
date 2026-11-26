"""HTTP API routers.

Routers are registered here so ``main.py`` only needs a single import.
New feature routers get their own module and are attached below.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api import documents, health, pages

api_router = APIRouter()

# Phase 1: health only. Phase 2+ routers are appended here.
api_router.include_router(health.router)
api_router.include_router(documents.router)
api_router.include_router(pages.router)
