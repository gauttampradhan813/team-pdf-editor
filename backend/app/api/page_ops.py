"""Page operations endpoints: rotate, delete, reorder."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from app.storage import DocumentNotFoundError, StorageError, storage

router = APIRouter(tags=["page-operations"], redirect_slashes=False)


class RotateRequest(BaseModel):
    page_numbers: list[int] = Field(
        ..., description="Zero-based page indices to rotate."
    )
    rotation: int = Field(
        ..., description="Rotation degrees: 90, 180, or 270."
    )


class DeleteRequest(BaseModel):
    page_numbers: list[int] = Field(
        ..., description="Zero-based page indices to delete."
    )


class ReorderRequest(BaseModel):
    page_order: list[int] = Field(
        ..., description="Complete list of zero-based original page indices "
        "in desired order."
    )


@router.post(
    "/documents/{document_id}/pages/rotate",
    summary="Rotate pages",
    status_code=status.HTTP_200_OK,
)
async def rotate_pages(document_id: str, payload: RotateRequest) -> JSONResponse:
    """Rotate selected pages clockwise by the given degrees."""
    try:
        record = storage.rotate_pages(
            document_id, payload.page_numbers, payload.rotation
        )
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    return JSONResponse(
        content={
            "document_id": record.document_id,
            "page_count": record.page_count,
            "message": f"Rotated pages {payload.page_numbers} by {payload.rotation} degrees.",
        }
    )


@router.post(
    "/documents/{document_id}/pages/delete",
    summary="Delete pages",
    status_code=status.HTTP_200_OK,
)
async def delete_pages(document_id: str, payload: DeleteRequest) -> JSONResponse:
    """Delete selected pages from the document."""
    try:
        record = storage.delete_pages(document_id, payload.page_numbers)
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    return JSONResponse(
        content={
            "document_id": record.document_id,
            "page_count": record.page_count,
            "message": f"Deleted {len(payload.page_numbers)} page(s).",
        }
    )


@router.post(
    "/documents/{document_id}/pages/reorder",
    summary="Reorder pages",
    status_code=status.HTTP_200_OK,
)
async def reorder_pages(document_id: str, payload: ReorderRequest) -> JSONResponse:
    """Reorder pages according to the supplied order."""
    try:
        record = storage.reorder_pages(document_id, payload.page_order)
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    return JSONResponse(
        content={
            "document_id": record.document_id,
            "page_count": record.page_count,
            "message": "Pages reordered.",
        }
    )
