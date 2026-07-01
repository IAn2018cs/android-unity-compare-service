from __future__ import annotations

import json
import shutil
from datetime import timedelta
from pathlib import Path

from app.config import Settings


class LocalReportStorage:
    def __init__(self, root: Path):
        self.root = Path(root)

    def upload_file(self, local_path: Path, key: str, content_type: str) -> None:
        target = self.root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_path, target)

    def signed_url(self, key: str, expires_in: int, filename: str) -> str | None:
        return None


class S3ReportStorage:
    def __init__(self, settings: Settings):
        import boto3

        self.bucket = settings.report_s3_bucket
        self.client = boto3.client(
            "s3",
            region_name=settings.report_s3_region,
            endpoint_url=settings.report_s3_endpoint_url,
            aws_access_key_id=settings.report_s3_access_key_id,
            aws_secret_access_key=settings.report_s3_secret_access_key,
        )

    def upload_file(self, local_path: Path, key: str, content_type: str) -> None:
        self.client.upload_file(str(local_path), self.bucket, key, ExtraArgs={"ContentType": content_type})

    def signed_url(self, key: str, expires_in: int, filename: str) -> str | None:
        return self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ResponseContentDisposition": f'attachment; filename="{filename}"',
            },
            ExpiresIn=expires_in,
        )


class GCSReportStorage:
    def __init__(self, settings: Settings):
        from google.cloud import storage

        credentials = settings.report_gcs_credentials_json
        if credentials and credentials.strip().startswith("{"):
            client = storage.Client.from_service_account_info(json.loads(credentials))
        elif credentials:
            client = storage.Client.from_service_account_json(credentials)
        else:
            client = storage.Client()
        self.bucket = client.bucket(settings.report_gcs_bucket)

    def upload_file(self, local_path: Path, key: str, content_type: str) -> None:
        self.bucket.blob(key).upload_from_filename(str(local_path), content_type=content_type)

    def signed_url(self, key: str, expires_in: int, filename: str) -> str | None:
        return self.bucket.blob(key).generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=expires_in),
            response_disposition=f'attachment; filename="{filename}"',
        )


def build_report_storage(settings: Settings):
    backend = settings.report_storage_backend.lower()
    if backend == "local":
        return LocalReportStorage(settings.data_dir / "reports")
    if backend == "s3":
        if not settings.report_s3_bucket:
            raise RuntimeError("REPORT_STORAGE_BACKEND=s3 需要配置 REPORT_S3_BUCKET。")
        return S3ReportStorage(settings)
    if backend == "gcs":
        if not settings.report_gcs_bucket:
            raise RuntimeError("REPORT_STORAGE_BACKEND=gcs 需要配置 REPORT_GCS_BUCKET。")
        return GCSReportStorage(settings)
    raise ValueError("REPORT_STORAGE_BACKEND 只能是 local/gcs/s3。")
