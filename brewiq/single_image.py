#!/usr/bin/env python3
"""Generate one Instagram still with the BrewIQ image chain and return a public URL.

Reuses art.openai_image (and fallbacks) plus host.upload_one_jpeg.
If GCS is not configured, hosts the JPEG through the linked Facebook Page CDN
so Instagram Graph API can fetch it.

Usage:
  python brewiq/single_image.py "Why AI agents need human approval"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
load_dotenv(ROOT / ".env")

from art import generate_illustrations  # noqa: E402
from host import to_jpeg, upload_one_jpeg  # noqa: E402


def _secret(*names: str) -> str:
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value and "your_" not in value and not value.endswith("_here"):
            return value
    return ""


def _image_prompt(topic: str) -> str:
    return (
        "Premium cinematic advertising still for Instagram. "
        "No text, no letters, no numbers, no logos, no watermarks, "
        "no interface, and no screenshots. "
        f"Topic: {topic}. "
        "Vertical 4:5 composition with a dark lower third and a clear focal subject."
    )


def _generate(topic: str):
    result = generate_illustrations([_image_prompt(topic)])
    if not result.get("ok"):
        return None, result.get("error") or "Image generation failed."
    images = result.get("images") or []
    if not images:
        return None, "Image generation returned no images."
    provider = result.get("provider") or "unknown"
    model = result.get("model") or ""
    label = f"{provider}:{model}" if model else provider
    return images[0], label


def _host_public(jpeg_path: Path) -> dict:
    """Host a JPEG on a public URL Instagram can fetch, without Page posting permission."""
    try:
        with jpeg_path.open("rb") as handle:
            response = requests.post(
                "https://catbox.moe/user/api.php",
                data={"reqtype": "fileupload"},
                files={"fileToUpload": ("brewiq.jpg", handle, "image/jpeg")},
                timeout=120,
            )
    except requests.RequestException:
        return {"ok": False, "url": "", "error": "The public image host could not be reached."}
    url = (response.text or "").strip()
    if response.status_code >= 400 or not url.startswith("https://"):
        return {"ok": False, "url": "", "error": "The public image host did not return a URL."}
    return {"ok": True, "url": url, "error": ""}


def _host_gcs(jpeg_path: Path) -> dict:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return upload_one_jpeg(jpeg_path, stamp)


def _page_token(page_id: str, user_token: str) -> str:
    """A user token can expose the Page token even when /me/accounts is empty."""
    try:
        response = requests.get(
            f"https://graph.facebook.com/v21.0/{page_id}",
            params={"fields": "access_token", "access_token": user_token},
            timeout=60,
        )
    except requests.RequestException:
        return ""
    body = response.json() if response.content else {}
    if response.status_code >= 400 or body.get("error"):
        return ""
    return str(body.get("access_token") or "").strip()


def _page_from_accounts(token: str, preferred: str) -> dict | None:
    """Return a Page from a user token. A Page token has no /me/accounts list."""
    try:
        accounts = requests.get(
            "https://graph.facebook.com/v21.0/me/accounts",
            params={
                "fields": "id,name,access_token,instagram_business_account",
                "access_token": token,
            },
            timeout=60,
        )
    except requests.RequestException:
        return None
    payload = accounts.json() if accounts.content else {}
    if accounts.status_code >= 400 or payload.get("error"):
        return None
    pages = payload.get("data") or []
    for item in pages:
        if preferred and str(item.get("id")) == preferred:
            return item
        if (item.get("name") or "").strip().lower() == "brew iq":
            return item
    if pages:
        return pages[0]
    return None


def _host_facebook(jpeg_path: Path) -> dict:
    token = _secret("INSTAGRAM_ACCESS_TOKEN", "IG_ACCESS_TOKEN")
    if not token:
        return {
            "ok": False,
            "url": "",
            "error": "No Instagram/Facebook token available for Page hosting.",
        }

    preferred = (os.getenv("FACEBOOK_PAGE_ID") or "").strip()
    page = _page_from_accounts(token, preferred)
    if not page and preferred:
        page_token = _page_token(preferred, token)
        if page_token:
            page = {"id": preferred, "access_token": page_token}
    if not page or not page.get("id"):
        return {"ok": False, "url": "", "error": "No Facebook Page was available for hosting."}

    page_token = page.get("access_token") or token
    with jpeg_path.open("rb") as handle:
        uploaded = requests.post(
            f"https://graph.facebook.com/v21.0/{page['id']}/photos",
            data={"published": "false", "access_token": page_token},
            files={"source": ("brewiq.jpg", handle, "image/jpeg")},
            timeout=120,
        )
    body = uploaded.json() if uploaded.content else {}
    if uploaded.status_code >= 400 or body.get("error") or not body.get("id"):
        message = body.get("error", {}).get("message") if isinstance(body.get("error"), dict) else ""
        return {"ok": False, "url": "", "error": message or "Facebook did not accept the image."}

    photo_id = body["id"]
    info = requests.get(
        f"https://graph.facebook.com/v21.0/{photo_id}",
        params={"fields": "images,source", "access_token": page_token},
        timeout=60,
    )
    details = info.json() if info.content else {}
    if info.status_code >= 400 or details.get("error"):
        message = details.get("error", {}).get("message") if isinstance(details.get("error"), dict) else ""
        return {"ok": False, "url": "", "error": message or "Could not read the hosted image URL."}

    url = (details.get("source") or "").strip()
    if not url:
        images = details.get("images") or []
        if images:
            url = (images[0].get("source") or "").strip()
    if not url:
        return {"ok": False, "url": "", "error": "Facebook returned no public image URL."}
    return {"ok": True, "url": url, "error": ""}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate one BrewIQ Instagram image")
    parser.add_argument("topic", help="Topic for the Instagram still")
    args = parser.parse_args()
    topic = args.topic.strip()
    if not topic:
        print(json.dumps({"ok": False, "url": "", "provider": "", "error": "Topic is required."}))
        return 1

    image, provider_or_error = _generate(topic)
    if image is None:
        print(
            json.dumps(
                {
                    "ok": False,
                    "url": "",
                    "provider": "",
                    "error": provider_or_error,
                }
            )
        )
        return 1
    provider = str(provider_or_error)

    with tempfile.TemporaryDirectory(prefix="brewiq-single-") as tmp:
        tmp_path = Path(tmp)
        png_path = tmp_path / "image.png"
        jpeg_path = tmp_path / "image.jpg"
        image.save(png_path)
        to_jpeg(png_path, jpeg_path)

        hosted = _host_gcs(jpeg_path)
        host = "gcs"
        if not hosted.get("ok"):
            hosted = _host_public(jpeg_path)
            host = "public"
        if not hosted.get("ok"):
            hosted = _host_facebook(jpeg_path)
            host = "facebook_page"
        if not hosted.get("ok"):
            print(
                json.dumps(
                    {
                        "ok": False,
                        "url": "",
                        "provider": provider,
                        "host": host,
                        "error": hosted.get("error")
                        or "Could not host a public image URL.",
                    }
                )
            )
            return 1

        print(
            json.dumps(
                {
                    "ok": True,
                    "url": hosted["url"],
                    "provider": provider,
                    "host": host,
                    "error": "",
                    "generated_at": int(time.time()),
                }
            )
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
