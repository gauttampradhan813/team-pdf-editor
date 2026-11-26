"""Document split endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, validator

from app.storage import DocumentNotFoundError, StorageError, storage

router = APIRouter(tags=["split"], redirect_slashes=False)


class SplitRequest(BaseModel):
    mode: str = Field(
        ...,
        description="Splitting mode: 'ranges', 'every_n_pages', or 'each_page'.",
    )
    ranges: list[list[int]] | None = Field(
        None,
        description="List of [start, end] zero-based inclusive page ranges "
        "(required for 'ranges' mode).",
    )
    pages_per_file: int | None = Field(
        None,
        description="Number of pages per output file "
        "(required for 'every_n_pages' mode).",
    )

    @validator("mode")
    def _validate_mode(cls, v):
        if v not in ("ranges", "every_n_pages", "each_page"):
            raise ValueError(
                "mode must be 'ranges', 'every_n_pages', or 'each_page'."
            )
        return v


@router.post(
    "/documents/{document_id}/split",
    summary="Split a PDF into multiple documents",
    status_code=status.HTTP_201_CREATED,
)
async def split_document(
    document_id: str, payload: SplitRequest
) -> JSONResponse:
    """Split a PDF into multiple new documents using one of three modes:
    custom page ranges, every N pages, or each page individually.

    The source document is never modified. Each output is registered as a
    new document with its own document ID.
    """
    try:
        result = storage.split_document(
            document_id,
            payload.mode,
            ranges=payload.ranges,
            pages_per_file=payload.pages_per_file,
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
        status_code=status.HTTP_201_CREATED,
        content={
            "source_document_id": result["source_document_id"],
            "total_files": result["total_files"],
            "total_pages": result["total_pages"],
            "outputs": result["outputs"],
        },
    )


@router.get(
    "/documents/split/download",
    summary="Download split outputs as a ZIP archive",
)
async def download_split_zip(document_ids: str = Query(...)) -> StreamingResponse:
    """Download multiple split output PDFs as a single ZIP archive.

    Args:
        document_ids: Comma-separated list of document IDs to include.

    Returns:
        A ZIP archive containing the selected PDFs.
    """
    id_list = [did.strip() for did in document_ids.split(",") if did.strip()]

    if not id_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one document ID is required.",
        )

    try:
        zip_bytes = storage.create_split_zip(id_list)
    except DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    return StreamingResponse(
        iter([zip_bytes]),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="split_outputs.zip"'
        },
    )
