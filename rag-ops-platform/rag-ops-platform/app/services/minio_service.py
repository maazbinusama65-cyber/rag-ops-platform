"""
MinIO service — handles all object storage operations.
"""

import io
from typing import Optional

from minio import Minio
from minio.error import S3Error

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class MinIOService:
    def __init__(self):
        self.client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        self._ensure_bucket()

    def _ensure_bucket(self):
        """Create the runbooks bucket if it doesn't exist."""
        try:
            if not self.client.bucket_exists(settings.MINIO_BUCKET):
                self.client.make_bucket(settings.MINIO_BUCKET)
                logger.info(f"✅ Created MinIO bucket: {settings.MINIO_BUCKET}")
            else:
                logger.info(f"✅ MinIO bucket exists: {settings.MINIO_BUCKET}")
        except S3Error as e:
            logger.error(f"❌ Failed to initialize MinIO bucket: {e}")
            raise

    def upload_file(
        self,
        object_key: str,
        file_data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload bytes to MinIO and return the object key."""
        try:
            file_stream = io.BytesIO(file_data)
            self.client.put_object(
                bucket_name=settings.MINIO_BUCKET,
                object_name=object_key,
                data=file_stream,
                length=len(file_data),
                content_type=content_type,
            )
            logger.info(f"✅ Uploaded to MinIO: {object_key} ({len(file_data)} bytes)")
            return object_key
        except S3Error as e:
            logger.error(f"❌ MinIO upload failed for {object_key}: {e}")
            raise

    def download_file(self, object_key: str) -> bytes:
        """Download an object from MinIO and return its bytes."""
        try:
            response = self.client.get_object(settings.MINIO_BUCKET, object_key)
            data = response.read()
            response.close()
            response.release_conn()
            logger.info(f"✅ Downloaded from MinIO: {object_key}")
            return data
        except S3Error as e:
            logger.error(f"❌ MinIO download failed for {object_key}: {e}")
            raise

    def list_objects(self, prefix: Optional[str] = None) -> list[str]:
        """List object keys in the runbooks bucket."""
        try:
            objects = self.client.list_objects(
                settings.MINIO_BUCKET, prefix=prefix, recursive=True
            )
            return [obj.object_name for obj in objects]
        except S3Error as e:
            logger.error(f"❌ MinIO list failed: {e}")
            raise

    def get_presigned_url(self, object_key: str, expires_hours: int = 1) -> str:
        """Generate a presigned URL for temporary access."""
        from datetime import timedelta
        return self.client.presigned_get_object(
            settings.MINIO_BUCKET,
            object_key,
            expires=timedelta(hours=expires_hours),
        )

    def health_check(self) -> bool:
        """Check MinIO connectivity."""
        try:
            self.client.list_buckets()
            return True
        except Exception:
            return False


# Singleton instance
minio_service = MinIOService()
