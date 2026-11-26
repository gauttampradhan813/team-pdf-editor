"""PDF compression endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator

from app.storage import DocumentNotFoundError, StorageError, storage

router = APIRouter(tags=["compression"], redirect_slashes=False)


from typing import Optional

from app.storage import DocumentNotFoundError, StorageError, storage

router = APIRouter(tags=["compression"], redirect_slashes=False)


class CompressRequest(BaseModel):
    level: str = Field(
        "medium",
        description="Compression level: 'low', 'medium', or 'high'.",
    )
    jpeg_quality: Optional[int] = Field(
        None,
        description="JPEG quality 1-100 (used for medium/high).",
    )
    max_image_dpi: Optional[int] = Field(
        None,
        description="Max image DPI for downsampling (high level).",
    )
    downsample_images: Optional[bool] = Field(
        None,
        description="Whether to downsample images (high level).",
    )

    @validator("level")
    def _validate_level(cls, v):
        if v not in ("low", "medium", "high"):
            raise ValueError(
                "level must be 'low', 'medium', or 'high'."
            )
        return v

    @validator("jpeg_quality")
    def _validate_quality(cls, v):
        if v is not None and not (1 <= v <= 100):
            raise ValueError("jpeg_quality must be between 1 and 100.")
        return v

    @validator("max_image_dpi")
    def _validate_dpi(cls, v):
        if v is not None and v < 1:
            raise ValueError("max_image_dpi must be >= 1.")
        return v

@router.post(
    "/documents/{document_id}/compress",
    summary="Compress a PDF document",
    status_code=status.HTTP_201_CREATED,
)
async def compress_document(
    document_id: str, payload: CompressRequest
) -> JSONResponse:
    """Compress a PDF document using pikepdf + Pillow.

    Three levels:
    - ``low``: structural optimization + stream compression,
      images kept at original quality.
    - ``medium``: structural optimization + stream compression +
      moderate JPEG recompression of eligible images.
    - ``high``: structural optimization + stronger image compression +
      optional downsampling to max_image_dpi.

    The source document is never modified. A new compressed document
    is registered with a new document ID.

    No page rasterization occurs.
    """
    try:
        result = storage.compress_document(
            document_id,
            payload.level,
            jpeg_quality=payload.jpeg_quality,
            max_image_dpi=payload.max_image_dpi,
            downsample_images=payload.downsample_images,
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
            "new_document_id": result["new_document_id"],
            "filename": result["filename"],
            "original_filename": result["original_filename"],
            "original_size": result["original_size"],
            "compressed_size": result["compressed_size"],
            "bytes_saved": result["bytes_saved"],
            "reduction_percent": result["reduction_percent"],
            "page_count": result["page_count"],
            "level": result["level"],
            "status": result["status"],
            "warnings": result["warnings"],
            "message": (
                f"Compressed {result['original_filename']} "
                f"({result['level']} level). "
                f"Saved {result['bytes_saved']} bytes "
                f"({result['reduction_percent']}% reduction)."
                if result["bytes_saved"] > 0
                else (
                    f"Compressed {result['original_filename']} "
                    f"({result['level']} level). "
                    f"Output is {abs(result['bytes_saved'])} bytes larger "
                    f"({abs(result['reduction_percent'])}% increase)."
                )
            ),
        },
    )
