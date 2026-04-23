"""
Document ingestion endpoint.
POST /api/v1/upload — accepts file, stores in MinIO, logs to PostgreSQL.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import get_logger
from app.core.metrics import documents_uploaded_total
from app.models.audit import DocumentUpload
from app.services.minio_service import minio_service

logger = get_logger(__name__)
router = APIRouter()

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "text/markdown",
    "text/plain",
    "text/x-markdown",
    "application/octet-stream",
}

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    x_user_id: str = Header(default="anonymous"),
):
    """
    Upload a document (PDF / Markdown / TXT) to MinIO object storage.

    - Validates file type and size
    - Pushes raw file to MinIO bucket `runbooks`
    - Logs the upload event to PostgreSQL `document_uploads` table
    - The Airflow pipeline will pick it up for embedding
    """
    # Validate content type (be lenient for octet-stream)
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        ext = (file.filename or "").split(".")[-1].lower()
        if ext not in {"pdf", "md", "txt", "markdown"}:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Unsupported file type: {file.content_type}. Allowed: PDF, Markdown, TXT",
            )

    # Read file contents
    file_data = await file.read()

    if len(file_data) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum allowed size is {MAX_FILE_SIZE // (1024*1024)} MB",
        )

    if len(file_data) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    # Generate a unique object key to avoid collisions
    file_ext = (file.filename or "file").split(".")[-1].lower()
    object_key = f"uploads/{datetime.utcnow().strftime('%Y/%m/%d')}/{uuid.uuid4()}.{file_ext}"

    try:
        # Push to MinIO
        minio_service.upload_file(
            object_key=object_key,
            file_data=file_data,
            content_type=file.content_type or "application/octet-stream",
        )

        # Log to PostgreSQL
        upload_record = DocumentUpload(
            filename=object_key,
            original_filename=file.filename or "unknown",
            file_size_bytes=len(file_data),
            content_type=file.content_type,
            minio_object_key=object_key,
            user_id=x_user_id,
            status="uploaded",
        )
        db.add(upload_record)
        await db.flush()

        # Track metric
        file_type = file_ext if file_ext in {"pdf", "md", "txt"} else "other"
        documents_uploaded_total.labels(file_type=file_type).inc()

        logger.info(
            f"📄 Document uploaded | user={x_user_id} | file={file.filename} | key={object_key}"
        )

        return {
            "message": "Document uploaded successfully. Pipeline will process it shortly.",
            "upload_id": str(upload_record.id),
            "object_key": object_key,
            "filename": file.filename,
            "file_size_bytes": len(file_data),
            "status": "uploaded",
        }

    except Exception as e:
        logger.error(f"❌ Upload failed for {file.filename}: {e}")
        # Log failure to DB
        error_record = DocumentUpload(
            filename=file.filename or "unknown",
            original_filename=file.filename or "unknown",
            file_size_bytes=len(file_data),
            content_type=file.content_type,
            minio_object_key=object_key,
            user_id=x_user_id,
            status="failed",
            error_message=str(e),
        )
        db.add(error_record)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(e)}",
        )


@router.get("/documents")
async def list_documents(db: AsyncSession = Depends(get_db)):
    """List all uploaded documents from MinIO."""
    try:
        objects = minio_service.list_objects()
        return {"documents": objects, "count": len(objects)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
