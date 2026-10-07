"""Turn slide PNGs into public JPEGs on the existing YouTube Cloud Storage bucket."""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
YOUTUBE_ROOT = ROOT.parent / "workflow_youtube_channel"
REVIEW = Path(__file__).resolve().parent / "review"

load_dotenv(ROOT / ".env")
if (YOUTUBE_ROOT / ".env").exists():
    load_dotenv(YOUTUBE_ROOT / ".env", override=False)


def _resolve_credentials(raw: str) -> Path | None:
    if not raw:
        return None
    path = Path(raw).expanduser()
    if path.is_file():
        return path
    for base in (ROOT, YOUTUBE_ROOT):
        candidate = base / raw
        if candidate.is_file():
            return candidate
    return None


def to_jpeg(png_path: Path, jpeg_path: Path) -> None:
    Image.open(png_path).convert("RGB").save(jpeg_path, "JPEG", quality=85, optimize=True)


def upload_jpegs(package_dir: Path, date_stamp: str) -> dict:
    """Upload slide-01.jpg through slide-06.jpg. Missing Cloud Storage config is a stop, not a guessed URL."""
    bucket_name = (os.getenv("GCS_BUCKET_NAME") or "").strip()
    prefix = (os.getenv("GCS_PUBLIC_URL_PREFIX") or "").rstrip("/")
    credentials = _resolve_credentials(
        os.getenv("GCS_SERVICE_ACCOUNT_PATH") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or ""
    )
    if not credentials:
        credentials = _resolve_credentials("credentials/gcs-service-account.json")
    pngs = sorted(package_dir.glob("slide-*.png"))
    if len(pngs) < 2:
        return {"ok": False, "urls": [], "error": "There are not enough slides to host."}
    if not bucket_name or credentials is None:
        return {
            "ok": False,
            "urls": [],
            "error": "Google Cloud Storage is not configured. Set GCS_BUCKET_NAME and the service-account path. No public URL was invented.",
        }
    if not prefix:
        prefix = f"https://storage.googleapis.com/{bucket_name}"
    try:
        from google.cloud import storage
        from google.oauth2 import service_account
    except ImportError:
        return {"ok": False, "urls": [], "error": "google-cloud-storage is not installed."}

    client = storage.Client(
        credentials=service_account.Credentials.from_service_account_file(str(credentials)),
    )
    bucket = client.bucket(bucket_name)
    urls = []
    for png in pngs:
        jpeg = png.with_suffix(".jpg")
        to_jpeg(png, jpeg)
        object_name = f"instagram/brewiq/{date_stamp}/{jpeg.name}"
        blob = bucket.blob(object_name)
        blob.upload_from_filename(str(jpeg), content_type="image/jpeg")
        try:
            blob.make_public()
        except Exception:
            pass
        urls.append(f"{prefix}/{object_name}")
    return {"ok": True, "urls": urls, "error": ""}


def upload_one_jpeg(jpeg_path: Path, date_stamp: str, object_name: str | None = None) -> dict:
    """Upload one JPEG for a single-image Instagram draft."""
    bucket_name = (os.getenv("GCS_BUCKET_NAME") or "").strip()
    prefix = (os.getenv("GCS_PUBLIC_URL_PREFIX") or "").rstrip("/")
    credentials = _resolve_credentials(
        os.getenv("GCS_SERVICE_ACCOUNT_PATH") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or ""
    )
    if not credentials:
        credentials = _resolve_credentials("credentials/gcs-service-account.json")
    if not jpeg_path.is_file():
        return {"ok": False, "url": "", "error": "JPEG file was not found."}
    if not bucket_name or credentials is None:
        return {
            "ok": False,
            "url": "",
            "error": "Google Cloud Storage is not configured. Set GCS_BUCKET_NAME and the service-account path.",
        }
    if not prefix:
        prefix = f"https://storage.googleapis.com/{bucket_name}"
    try:
        from google.cloud import storage
        from google.oauth2 import service_account
    except ImportError:
        return {"ok": False, "url": "", "error": "google-cloud-storage is not installed."}

    client = storage.Client(
        credentials=service_account.Credentials.from_service_account_file(str(credentials)),
    )
    bucket = client.bucket(bucket_name)
    blob_name = object_name or f"instagram/brewiq/{date_stamp}/{jpeg_path.name}"
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(str(jpeg_path), content_type="image/jpeg")
    try:
        blob.make_public()
    except Exception:
        pass
    return {"ok": True, "url": f"{prefix}/{blob_name}", "error": ""}


def write_review(package_dir: Path, caption: str, urls: list[str], provider: str, hosted_ok: bool, error: str = "") -> Path:
    REVIEW.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": package_dir.name,
        "package_dir": str(package_dir),
        "caption": caption,
        "jpeg_urls": urls,
        "provider": provider,
        "ready": hosted_ok and len(urls) >= 2,
        "published": False,
        "media_id": "",
        "error": error,
    }
    path = REVIEW / "latest.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def load_review() -> dict:
    path = REVIEW / "latest.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def mark_published(media_id: str) -> None:
    payload = load_review()
    payload["published"] = True
    payload["media_id"] = media_id
    payload["error"] = ""
    (REVIEW / "latest.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
