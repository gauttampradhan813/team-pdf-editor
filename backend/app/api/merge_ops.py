"""Document merge endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.storage import DocumentNotFoundError, StorageError, storage

router = APIRouter(tags=["merge"], redirect_slashes=False)


class MergeRequest(BaseModel):
    document_ids: list[str] = Field(
        ...,
        description="Ordered list of document IDs to merge (2 or more).",
        min_length=2,
    )


@router.post(
    "/documents/merge",
    summary="Merge multiple PDFs into one document",
    status_code=status.HTTP_201_CREATED,
)
async def merge_documents(payload: MergeRequest) -> JSONResponse:
    """Merge multiple stored PDFs into a single new document.

    The source documents are never modified. A new document ID is
    created for the merged result.
    """
    try:
        new_record = storage.merge_documents(
            payload.document_ids,
            filename="merged.pdf",
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
            "document_id": new_record.document_id,
            "filename": new_record.filename,
            "page_count": new_record.page_count,
            "file_size": new_record.size,
            "message": f"Merged {len(payload.document_ids)} document(s).",
        },
    )
