from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .urls import safe_filename


class CacheStore:
    def __init__(self, root: Path):
        self.root = root
        self.pages_dir = root / "pages"
        self.assets_dir = root / "assets"

    def page_path(self, slug: str) -> Path:
        return self.pages_dir / f"{safe_filename(slug)}.html"

    def page_metadata_path(self, slug: str) -> Path:
        return self.pages_dir / f"{safe_filename(slug)}.json"

    def has_page(self, slug: str) -> bool:
        return self.page_path(slug).exists()

    def read_page(self, slug: str) -> str:
        return self.page_path(slug).read_text(encoding="utf-8")

    def write_page(self, slug: str, url: str, text: str, status_code: int, content_type: str) -> tuple[Path, Path]:
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        page_path = self.page_path(slug)
        meta_path = self.page_metadata_path(slug)
        page_path.write_text(text, encoding="utf-8")
        meta_path.write_text(
            json.dumps(
                {
                    "url": url,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "status_code": status_code,
                    "content_type": content_type,
                    "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return page_path, meta_path

    def asset_path(self, url: str, content_type: str = "") -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        suffix = _suffix_from_content_type(content_type) or Path(urlparse(url).path).suffix or ".bin"
        return self.assets_dir / f"{digest}{suffix}"

    def write_asset(self, url: str, content: bytes, status_code: int, content_type: str) -> tuple[Path, Path]:
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        asset_path = self.asset_path(url, content_type)
        meta_path = asset_path.with_suffix(asset_path.suffix + ".json")
        asset_path.write_bytes(content)
        meta_path.write_text(
            json.dumps(
                {
                    "url": url,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "status_code": status_code,
                    "content_type": content_type,
                    "sha256": hashlib.sha256(content).hexdigest(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return asset_path, meta_path


def _suffix_from_content_type(content_type: str) -> str:
    content_type = content_type.split(";")[0].strip().lower()
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "text/css": ".css",
        "font/woff": ".woff",
        "font/woff2": ".woff2",
    }.get(content_type, "")
