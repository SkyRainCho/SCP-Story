from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib import error, request

from .cache import CacheStore
from .models import FetchResult


@dataclass(frozen=True)
class _Response:
    content: bytes
    status_code: int
    content_type: str


BrowserFetchData = str | tuple[str, int, str | None]


class SessionHTTPClient(Protocol):
    def get(self, url: str, *, headers: dict[str, str]) -> Any:
        ...


HTTPClient = Callable[..., Any] | SessionHTTPClient


class BrowserFetcher(Protocol):
    def fetch(self, url: str) -> BrowserFetchData:
        ...


class FetchError(Exception):
    def __init__(
        self,
        url: str,
        *,
        status_code: int | None = None,
        reason: str | None = None,
    ):
        self.url = url
        self.status_code = status_code
        self.reason = reason
        details = []
        if status_code is not None:
            details.append(f"status={status_code}")
        if reason:
            details.append(f"reason={reason}")
        suffix = f" ({', '.join(details)})" if details else ""
        super().__init__(f"Failed to fetch {url}{suffix}")


class Fetcher:
    DEFAULT_USER_AGENT = "scp-story-epub/0.1"

    def __init__(
        self,
        cache: CacheStore,
        *,
        http_client: HTTPClient | None = None,
        browser_fetcher: BrowserFetcher | Callable[[str], BrowserFetchData] | None = None,
        retry_count: int = 3,
        asset_retry_count: int | None = None,
        request_delay_seconds: float = 0.0,
        request_timeout_seconds: float = 30.0,
        asset_timeout_seconds: float | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
    ):
        if retry_count < 1:
            raise ValueError("retry_count must be at least 1")
        if asset_retry_count is not None and asset_retry_count < 1:
            raise ValueError("asset_retry_count must be at least 1")
        if request_delay_seconds < 0:
            raise ValueError("request_delay_seconds must be non-negative")
        if request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        if asset_timeout_seconds is not None and asset_timeout_seconds <= 0:
            raise ValueError("asset_timeout_seconds must be positive")
        self.cache = cache
        self.http_client = http_client
        self.browser_fetcher = browser_fetcher
        self.retry_count = retry_count
        self.asset_retry_count = asset_retry_count or retry_count
        self.request_delay_seconds = request_delay_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self.asset_timeout_seconds = asset_timeout_seconds or request_timeout_seconds
        self.user_agent = user_agent

    def fetch_page(self, slug: str, url: str, *, force: bool = False) -> FetchResult:
        if not force and self.cache.has_page(slug):
            metadata = self._read_metadata(
                self.cache.page_metadata_path(slug),
                default_status_code=200,
                default_content_type="text/html",
            )
            return FetchResult(
                url=url,
                path=self.cache.page_path(slug),
                metadata_path=self.cache.page_metadata_path(slug),
                from_cache=True,
                status_code=metadata["status_code"],
                content_type=metadata["content_type"],
            )

        try:
            response = self._get_with_retries(
                url,
                retry_count=self.retry_count,
                timeout_seconds=self.request_timeout_seconds,
            )
        except FetchError as http_error:
            if self.browser_fetcher is None:
                raise http_error
            try:
                html, status_code, content_type = self._fetch_with_browser(url)
            except Exception as browser_error:
                reason = (
                    f"{http_error.reason or http_error}; "
                    f"browser fallback failed: {browser_error}"
                )
                raise FetchError(
                    url,
                    status_code=http_error.status_code,
                    reason=reason,
                ) from browser_error
            page_path, metadata_path = self.cache.write_page(
                slug,
                url,
                html,
                status_code,
                content_type or "text/html",
            )
            return FetchResult(
                url=url,
                path=page_path,
                metadata_path=metadata_path,
                from_cache=False,
                status_code=status_code,
                content_type=content_type or "text/html",
            )

        content_type = response.content_type or "text/html"
        page_path, metadata_path = self.cache.write_page(
            slug,
            url,
            self._decode_text(response.content, content_type),
            response.status_code,
            content_type,
        )
        return FetchResult(
            url=url,
            path=page_path,
            metadata_path=metadata_path,
            from_cache=False,
            status_code=response.status_code,
            content_type=content_type,
        )

    def fetch_asset(self, url: str, *, force: bool = False) -> FetchResult:
        if not force:
            cached_path = self.cache.find_asset(url)
            if cached_path is not None:
                metadata_path = cached_path.with_suffix(cached_path.suffix + ".json")
                metadata = self._read_metadata(
                    metadata_path,
                    default_status_code=200,
                    default_content_type="application/octet-stream",
                )
                return FetchResult(
                    url=url,
                    path=cached_path,
                    metadata_path=metadata_path,
                    from_cache=True,
                    status_code=metadata["status_code"],
                    content_type=metadata["content_type"],
                )

        response = self._get_with_retries(
            url,
            retry_count=self.asset_retry_count,
            timeout_seconds=self.asset_timeout_seconds,
        )
        content_type = response.content_type or "application/octet-stream"
        if force:
            self.cache.delete_asset(url)
        asset_path, metadata_path = self.cache.write_asset(
            url,
            response.content,
            response.status_code,
            content_type,
        )
        return FetchResult(
            url=url,
            path=asset_path,
            metadata_path=metadata_path,
            from_cache=False,
            status_code=response.status_code,
            content_type=content_type,
        )

    def _get_with_retries(
        self,
        url: str,
        *,
        retry_count: int,
        timeout_seconds: float,
    ) -> _Response:
        last_error: FetchError | None = None
        headers = {"User-Agent": self.user_agent}
        for attempt in range(1, retry_count + 1):
            try:
                response = self._normalize_response(
                    self._call_http_client(url, headers, timeout_seconds)
                )
                if response.status_code >= 400:
                    raise FetchError(url, status_code=response.status_code, reason="HTTP error")
                return response
            except FetchError as exc:
                last_error = exc
            except Exception as exc:
                last_error = FetchError(url, reason=str(exc))

            if attempt < retry_count and self.request_delay_seconds:
                time.sleep(self.request_delay_seconds)

        if last_error is None:
            raise FetchError(url, reason="unknown error")
        raise last_error

    def _call_http_client(
        self,
        url: str,
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> Any:
        if self.http_client is None:
            return self._urllib_get(url, headers=headers, timeout_seconds=timeout_seconds)

        get = getattr(self.http_client, "get", None)
        if callable(get):
            return get(url, headers=headers)
        if callable(self.http_client):
            return self.http_client(url, headers=headers)
        raise TypeError("HTTP client must be callable or provide get()")

    def _fetch_with_browser(self, url: str) -> tuple[str, int, str]:
        fetcher = self.browser_fetcher
        if fetcher is None:
            raise FetchError(url, reason="browser fallback is not configured")
        raw = fetcher.fetch(url) if hasattr(fetcher, "fetch") else fetcher(url)
        if isinstance(raw, tuple):
            html, status_code, content_type = raw
            return html, status_code, content_type or "text/html"
        return raw, 200, "text/html"

    def _urllib_get(
        self,
        url: str,
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> _Response:
        req = request.Request(url, headers=headers, method="GET")
        try:
            with request.urlopen(req, timeout=timeout_seconds) as response:
                return _Response(
                    content=response.read(),
                    status_code=response.status,
                    content_type=response.headers.get("Content-Type", ""),
                )
        except error.HTTPError as exc:
            return _Response(
                content=exc.read(),
                status_code=exc.code,
                content_type=exc.headers.get("Content-Type", ""),
            )
        except error.URLError as exc:
            raise FetchError(url, reason=str(exc.reason)) from exc

    def _normalize_response(self, response: Any) -> _Response:
        if isinstance(response, _Response):
            return response
        if isinstance(response, tuple) and len(response) == 3:
            content, status_code, content_type = response
            return _Response(
                content=_to_bytes(content),
                status_code=int(status_code),
                content_type="" if content_type is None else str(content_type),
            )

        status_code = getattr(response, "status_code", getattr(response, "status", None))
        if status_code is None:
            raise ValueError("HTTP response must provide a status code")

        content = getattr(response, "content", None)
        if content is None and hasattr(response, "read"):
            content = response.read()
        if content is None and hasattr(response, "text"):
            content = response.text
        if content is None:
            content = b""

        content_type = _header_value(getattr(response, "headers", {}), "content-type")
        return _Response(
            content=_to_bytes(content),
            status_code=int(status_code),
            content_type=content_type,
        )

    def _read_metadata(
        self,
        metadata_path: Path,
        *,
        default_status_code: int,
        default_content_type: str,
    ) -> dict[str, Any]:
        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                return {
                    "status_code": int(metadata.get("status_code", default_status_code)),
                    "content_type": str(metadata.get("content_type") or default_content_type),
                }
            except (OSError, ValueError, TypeError):
                pass
        return {
            "status_code": default_status_code,
            "content_type": default_content_type,
        }

    def _decode_text(self, content: bytes, content_type: str) -> str:
        charset = "utf-8"
        for part in content_type.split(";")[1:]:
            key, separator, value = part.strip().partition("=")
            if separator and key.lower() == "charset" and value.strip():
                charset = value.strip().strip('"')
                break
        try:
            return content.decode(charset, errors="replace")
        except LookupError:
            return content.decode("utf-8", errors="replace")


def _to_bytes(content: Any) -> bytes:
    if isinstance(content, bytes):
        return content
    if isinstance(content, bytearray):
        return bytes(content)
    if isinstance(content, str):
        return content.encode("utf-8")
    return bytes(content)


def _header_value(headers: Mapping[str, Any], name: str) -> str:
    for key, value in headers.items():
        if str(key).lower() == name.lower():
            return str(value)
    return ""
