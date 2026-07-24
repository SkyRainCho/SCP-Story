import json
from pathlib import Path

import pytest

from scp_epub.cache import CacheStore
from scp_epub.fetcher import FetchError, Fetcher


class RecordingClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: dict[str, str]):
        self.calls.append((url, dict(headers)))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_fetch_page_returns_cache_hit_without_http_and_reads_metadata(tmp_path: Path):
    cache = CacheStore(tmp_path / "raw")
    cache.write_page(
        "scp-002",
        "https://example.test/scp-002",
        "<html>cached</html>",
        203,
        "text/html; charset=utf-8",
    )
    client = RecordingClient([AssertionError("HTTP client should not be called")])

    result = Fetcher(cache, http_client=client).fetch_page(
        "scp-002",
        "https://example.test/scp-002",
    )

    assert result.from_cache is True
    assert result.path == cache.page_path("scp-002")
    assert result.metadata_path == cache.page_metadata_path("scp-002")
    assert result.status_code == 203
    assert result.content_type == "text/html; charset=utf-8"
    assert result.path.read_text(encoding="utf-8") == "<html>cached</html>"
    assert client.calls == []


def test_fetch_page_downloads_missing_page_and_writes_metadata(tmp_path: Path):
    cache = CacheStore(tmp_path / "raw")
    client = RecordingClient(
        [
            (
                b"<html>network</html>",
                200,
                "text/html; charset=utf-8",
            )
        ]
    )

    result = Fetcher(cache, http_client=client).fetch_page(
        "scp-002",
        "https://example.test/scp-002",
    )

    assert result.from_cache is False
    assert result.status_code == 200
    assert result.content_type == "text/html; charset=utf-8"
    assert result.path.read_text(encoding="utf-8") == "<html>network</html>"
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["url"] == "https://example.test/scp-002"
    assert metadata["status_code"] == 200
    assert metadata["content_type"] == "text/html; charset=utf-8"
    assert client.calls == [
        (
            "https://example.test/scp-002",
            {"User-Agent": Fetcher.DEFAULT_USER_AGENT},
        )
    ]


def test_fetch_page_accepts_session_like_http_client(tmp_path: Path):
    class Response:
        status_code = 200
        content = b"<html>session</html>"
        headers = {"content-type": "text/html"}

    class SessionClient:
        def __init__(self):
            self.calls: list[tuple[str, dict[str, str]]] = []

        def get(self, url: str, headers: dict[str, str]):
            self.calls.append((url, dict(headers)))
            return Response()

    cache = CacheStore(tmp_path / "raw")
    session = SessionClient()

    result = Fetcher(cache, http_client=session).fetch_page(
        "scp-002",
        "https://example.test/scp-002",
    )

    assert result.path.read_text(encoding="utf-8") == "<html>session</html>"
    assert session.calls == [
        (
            "https://example.test/scp-002",
            {"User-Agent": Fetcher.DEFAULT_USER_AGENT},
        )
    ]


def test_fetch_page_accepts_keyword_only_callable_http_client(tmp_path: Path):
    calls: list[tuple[str, dict[str, str]]] = []

    def client(url: str, *, headers: dict[str, str]):
        calls.append((url, dict(headers)))
        return b"<html>keyword callable</html>", 200, "text/html"

    cache = CacheStore(tmp_path / "raw")

    result = Fetcher(cache, http_client=client).fetch_page(
        "scp-002",
        "https://example.test/scp-002",
    )

    assert result.path.read_text(encoding="utf-8") == "<html>keyword callable</html>"
    assert calls == [
        (
            "https://example.test/scp-002",
            {"User-Agent": Fetcher.DEFAULT_USER_AGENT},
        )
    ]


def test_fetch_page_passes_configured_timeout_to_urllib(tmp_path: Path, monkeypatch):
    captured: dict[str, float] = {}

    class Response:
        status = 200
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b"<html>timeout</html>"

    def urlopen(_request, *, timeout: float):
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("scp_epub.fetcher.request.urlopen", urlopen)
    cache = CacheStore(tmp_path / "raw")

    Fetcher(cache, request_timeout_seconds=7).fetch_page(
        "scp-002",
        "https://example.test/scp-002",
    )

    assert captured["timeout"] == 7


def test_fetch_asset_uses_asset_specific_retry_count(tmp_path: Path):
    cache = CacheStore(tmp_path / "raw")
    client = RecordingClient(
        [
            OSError("temporary failure"),
            (b"png bytes", 200, "image/png"),
        ]
    )

    with pytest.raises(FetchError):
        Fetcher(cache, http_client=client, retry_count=2, asset_retry_count=1).fetch_asset(
            "https://example.test/assets/logo.png"
        )

    assert len(client.calls) == 1


def test_fetch_page_prefers_get_when_http_client_is_also_callable(tmp_path: Path):
    class Response:
        status_code = 200
        content = b"<html>get path</html>"
        headers = {"content-type": "text/html"}

    class DualClient:
        def __init__(self):
            self.calls: list[tuple[str, dict[str, str]]] = []

        def __call__(self, url: str, *, headers: dict[str, str]):
            raise AssertionError("__call__ should not be used when get() exists")

        def get(self, url: str, *, headers: dict[str, str]):
            self.calls.append((url, dict(headers)))
            return Response()

    cache = CacheStore(tmp_path / "raw")
    client = DualClient()

    result = Fetcher(cache, http_client=client).fetch_page(
        "scp-002",
        "https://example.test/scp-002",
    )

    assert result.path.read_text(encoding="utf-8") == "<html>get path</html>"
    assert client.calls == [
        (
            "https://example.test/scp-002",
            {"User-Agent": Fetcher.DEFAULT_USER_AGENT},
        )
    ]


def test_fetch_page_uses_browser_fallback_after_http_failure_and_caches_html(tmp_path: Path):
    cache = CacheStore(tmp_path / "raw")
    client = RecordingClient([(b"server error", 500, "text/plain")])
    browser_calls: list[str] = []

    def browser_fetcher(url: str):
        browser_calls.append(url)
        return "<html>browser</html>", 200, ""

    result = Fetcher(
        cache,
        http_client=client,
        browser_fetcher=browser_fetcher,
        retry_count=1,
    ).fetch_page("scp-002", "https://example.test/scp-002")

    assert result.from_cache is False
    assert result.status_code == 200
    assert result.content_type == "text/html"
    assert result.path.read_text(encoding="utf-8") == "<html>browser</html>"
    assert cache.read_page("scp-002") == "<html>browser</html>"
    assert browser_calls == ["https://example.test/scp-002"]


def test_fetch_page_raises_fetch_error_when_http_and_fallback_fail(tmp_path: Path):
    cache = CacheStore(tmp_path / "raw")
    client = RecordingClient([(b"server error", 503, "text/plain")])

    with pytest.raises(FetchError) as exc_info:
        Fetcher(cache, http_client=client, retry_count=1).fetch_page(
            "scp-002",
            "https://example.test/scp-002",
        )

    assert exc_info.value.url == "https://example.test/scp-002"
    assert exc_info.value.status_code == 503
    assert "https://example.test/scp-002" in str(exc_info.value)


def test_fetch_page_invalid_charset_falls_back_to_utf8_replacement(tmp_path: Path):
    cache = CacheStore(tmp_path / "raw")
    client = RecordingClient(
        [
            (
                "<html>中文</html>".encode("utf-8"),
                200,
                "text/html; charset=not-a-codec",
            )
        ]
    )

    result = Fetcher(cache, http_client=client).fetch_page(
        "scp-002",
        "https://example.test/scp-002",
    )

    assert result.path.read_text(encoding="utf-8") == "<html>中文</html>"


def test_fetch_asset_downloads_bytes_and_cache_hit_avoids_http(tmp_path: Path):
    cache = CacheStore(tmp_path / "raw")
    url = "https://example.test/assets/logo.png"
    first_client = RecordingClient([(b"png bytes", 200, "image/png")])

    first = Fetcher(cache, http_client=first_client).fetch_asset(url)

    assert first.from_cache is False
    assert first.status_code == 200
    assert first.content_type == "image/png"
    assert first.path.read_bytes() == b"png bytes"
    metadata = json.loads(first.metadata_path.read_text(encoding="utf-8"))
    assert metadata["url"] == url
    assert metadata["content_type"] == "image/png"

    second_client = RecordingClient([AssertionError("HTTP client should not be called")])
    second = Fetcher(cache, http_client=second_client).fetch_asset(url)

    assert second.from_cache is True
    assert second.path == first.path
    assert second.metadata_path == first.metadata_path
    assert second.status_code == 200
    assert second.content_type == "image/png"
    assert second_client.calls == []


def test_fetch_asset_force_refresh_removes_stale_digest_files(tmp_path: Path):
    cache = CacheStore(tmp_path / "raw")
    url = "https://example.test/assets/logo"
    fetcher = Fetcher(
        cache,
        http_client=RecordingClient(
            [
                (b"png bytes", 200, "image/png"),
                (b"webp bytes", 200, "image/webp"),
            ]
        ),
    )

    png = fetcher.fetch_asset(url)
    assert cache.find_asset(url) == png.path

    webp = fetcher.fetch_asset(url, force=True)
    cached = fetcher.fetch_asset(url)

    assert png.path.suffix == ".png"
    assert webp.path.suffix == ".webp"
    assert cached.from_cache is True
    assert cached.path == webp.path
    assert cached.path.read_bytes() == b"webp bytes"
    assert not png.path.exists()
    assert not png.metadata_path.exists()


def test_fetch_page_retries_until_retry_count_total_attempts(tmp_path: Path):
    cache = CacheStore(tmp_path / "raw")
    client = RecordingClient(
        [
            OSError("temporary failure"),
            (b"<html>retry success</html>", 200, "text/html"),
        ]
    )

    result = Fetcher(cache, http_client=client, retry_count=2).fetch_page(
        "scp-002",
        "https://example.test/scp-002",
    )

    assert result.path.read_text(encoding="utf-8") == "<html>retry success</html>"
    assert len(client.calls) == 2


def test_fetch_page_does_not_retry_permanent_4xx_errors(tmp_path: Path):
    cache = CacheStore(tmp_path / "raw")
    client = RecordingClient(
        [
            (b"not found", 404, "text/plain"),
            AssertionError("a permanent 404 must not be retried"),
        ]
    )

    with pytest.raises(FetchError) as exc_info:
        Fetcher(
            cache,
            http_client=client,
            retry_count=3,
            request_delay_seconds=0.0,
        ).fetch_page("scp-002", "https://example.test/scp-002")

    assert exc_info.value.status_code == 404
    assert len(client.calls) == 1


def test_fetch_page_retries_5xx_server_errors(tmp_path: Path):
    cache = CacheStore(tmp_path / "raw")
    client = RecordingClient([(b"server error", 500, "text/plain")] * 3)

    with pytest.raises(FetchError) as exc_info:
        Fetcher(
            cache,
            http_client=client,
            retry_count=3,
            request_delay_seconds=0.0,
        ).fetch_page("scp-002", "https://example.test/scp-002")

    assert exc_info.value.status_code == 500
    assert len(client.calls) == 3
