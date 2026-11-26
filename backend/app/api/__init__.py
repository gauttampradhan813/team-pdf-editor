"""HTTP API routers.

Routers are registered here so ``main.py`` only needs a single import.
New feature routers get their own module and are attached below.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api import documents, health, merge_ops, page_ops, pages, split_ops, compress_ops

api_router = APIRouter()

# Phase 1: health only. Phase 2+ routers are appended here.
# NOTE: split_ops must be registered before documents so that
# /documents/split/download is matched before /documents/{document_id}/download.
api_router.include_router(health.router)
api_router.include_router(split_ops.router)
api_router.include_router(documents.router)
api_router.include_router(pages.router)
api_router.include_router(page_ops.router)
api_router.include_router(merge_ops.router)
api_router.include_router(compress_ops.router)
