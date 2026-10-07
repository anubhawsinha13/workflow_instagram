"""Publish one carousel with Instagram Login. This never runs unless --publish is passed."""

from __future__ import annotations

import os
import time

import requests
from dotenv import load_dotenv

from host import ROOT

load_dotenv(ROOT / ".env")

TIMEOUT = 90


def _secret(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value or "your_" in value or value.endswith("_here"):
        return ""
    return value


def _base() -> str:
    version = (os.getenv("IG_GRAPH_VERSION") or "v21.0").strip()
    return f"https://graph.instagram.com/{version}"


def _post(path: str, data: dict, token: str, http) -> dict:
    response = http.post(
        f"{_base()}/{path}",
        data=data,
        params={"access_token": token},
        timeout=TIMEOUT,
    )
    payload = response.json() if response.content else {}
    if response.status_code >= 400 or payload.get("error"):
        message = payload.get("error", {}).get("message") if isinstance(payload.get("error"), dict) else response.text
        return {"ok": False, "error": message or f"Instagram returned {response.status_code}."}
    return {"ok": True, **payload}


def _wait_until_ready(container_id: str, token: str, http, sleep) -> dict:
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        response = http.get(
            f"{_base()}/{container_id}",
            params={"fields": "status_code", "access_token": token},
            timeout=TIMEOUT,
        )
        payload = response.json() if response.content else {}
        status = payload.get("status_code") or "FINISHED"
        if status == "FINISHED":
            return {"ok": True}
        if status == "ERROR":
            return {"ok": False, "error": "Instagram could not process one of the images."}
        sleep(3)
    return {"ok": False, "error": "Instagram did not finish processing the image in time."}


def publish_carousel(image_urls: list[str], caption: str, http=requests, sleep=time.sleep) -> dict:
    token = _secret("IG_ACCESS_TOKEN")
    user_id = _secret("IG_USER_ID")
    if not token or not user_id:
        return {
            "ok": False,
            "error": "Instagram is not configured. Set IG_ACCESS_TOKEN and IG_USER_ID. Nothing was posted.",
        }
    if not 2 <= len(image_urls) <= 10:
        return {"ok": False, "error": "A carousel needs between 2 and 10 public JPEG URLs. Nothing was posted."}

    child_ids = []
    for url in image_urls:
        created = _post(f"{user_id}/media", {"image_url": url, "is_carousel_item": "true"}, token, http)
        if not created.get("ok") or not created.get("id"):
            return {"ok": False, "error": created.get("error") or "Instagram did not accept an image. Nothing was posted."}
        ready = _wait_until_ready(created["id"], token, http, sleep)
        if not ready.get("ok"):
            return {"ok": False, "error": ready.get("error") or "An image was not ready. Nothing was posted."}
        child_ids.append(created["id"])

    carousel = _post(
        f"{user_id}/media",
        {"media_type": "CAROUSEL", "children": ",".join(child_ids), "caption": caption},
        token,
        http,
    )
    if not carousel.get("ok") or not carousel.get("id"):
        return {"ok": False, "error": carousel.get("error") or "Instagram did not accept the carousel. Nothing was posted."}
    ready = _wait_until_ready(carousel["id"], token, http, sleep)
    if not ready.get("ok"):
        return ready
    published = _post(f"{user_id}/media_publish", {"creation_id": carousel["id"]}, token, http)
    if not published.get("ok") or not published.get("id"):
        return {"ok": False, "error": published.get("error") or "Instagram did not publish the carousel."}
    return {"ok": True, "media_id": published["id"], "error": ""}
