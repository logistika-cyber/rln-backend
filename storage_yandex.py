import os
import boto3
from botocore.client import Config
from fastapi import UploadFile

YANDEX_S3_ENDPOINT = os.getenv("YANDEX_S3_ENDPOINT", "https://storage.yandexcloud.net")
YANDEX_S3_BUCKET = os.getenv("YANDEX_S3_BUCKET", "rlngroup")
YANDEX_S3_ACCESS_KEY = os.getenv("YANDEX_S3_ACCESS_KEY_ID")
YANDEX_S3_SECRET_KEY = os.getenv("YANDEX_S3_SECRET_ACCESS_KEY")

session = boto3.session.Session()

s3_client = session.client(
    "s3",
    endpoint_url=YANDEX_S3_ENDPOINT,
    aws_access_key_id=YANDEX_S3_ACCESS_KEY,
    aws_secret_access_key=YANDEX_S3_SECRET_KEY,
    config=Config(signature_version="s3v4"),
)


async def upload_file_to_yandex(file: UploadFile, object_name: str) -> str:
    file_bytes = await file.read()

    content_type = file.content_type or "application/octet-stream"

    s3_client.put_object(
        Bucket=YANDEX_S3_BUCKET,
        Key=object_name,
        Body=file_bytes,
        ContentType=content_type,
    )

    return f"{YANDEX_S3_ENDPOINT}/{YANDEX_S3_BUCKET}/{object_name}"
