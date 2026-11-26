"""PDF page rendering endpoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response

from app.config import get_settings
from app.storage import DocumentNotFoundError, DocumentStorage

router = APIRouter(tags=["pages"])

storage = DocumentStorage()


@router.get(
    "/documents/{document_id}/pages/{page_number}.png",
    summary="Render a PDF page as PNG",
    responses={
        200: {"content": {"image/png": {}}, "description": "PNG image of the page"},
    },
)
def render_page(
    document_id: str,
    page_number: int,
    scale: float | None = Query(
        None,
        gt=0,
        le=4,
        description="Render scale (1.0 = 72 DPI, 2.0 = 144 DPI, etc.). "
        "Defaults to TEAMPDF_DEFAULT_RENDER_SCALE.",
    ),
) -> Response:
    """Render a single PDF page to PNG using PyMuPDF.

    Only the requested page is loaded into memory. Rendered output is
    cached per document, page number and scale.
    """
    settings = get_settings()
    render_scale = scale if scale is not None else settings.default_render_scale

    try:
        png_bytes = storage.page_png(document_id, page_number, render_scale)
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    return Response(content=png_bytes, media_type="image/png")
