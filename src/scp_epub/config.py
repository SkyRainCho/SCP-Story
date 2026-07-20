from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from .models import (
    AppendixSection,
    AppendixSpec,
    AppConfig,
    ConfiguredLink,
    ConfiguredPage,
    InlineDocumentSpec,
    PageFallback,
    PageOverride,
    VolumeSpec,
)
from .urls import normalize_url, slug_from_url


REQUIRED_TOP_LEVEL = {
    "series_id",
    "title",
    "language",
    "creator",
    "base_url",
    "index_path",
    "series_index_path",
    "scp001_path",
    "cache_dir",
    "manifest_dir",
    "processed_dir",
    "output_dir",
    "request_delay_seconds",
    "retry_count",
    "volumes",
}


REQUIRED_VOLUME_KEYS = {"start", "end", "title", "output_slug"}
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}\Z")


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).resolve()
    raw_data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data = _mapping({} if raw_data is None else raw_data, "config")
    missing = sorted(REQUIRED_TOP_LEVEL - set(data))
    if missing:
        raise ValueError(f"Config missing required keys: {', '.join(missing)}")

    volumes = _load_volumes(data["volumes"])

    workspace = config_path.parent.parent if config_path.parent.name == "config" else config_path.parent

    return AppConfig(
        workspace=workspace,
        series_id=_required_string(data["series_id"], "series_id"),
        title=_required_string(data["title"], "title"),
        language=_required_string(data["language"], "language"),
        creator=_required_string(data["creator"], "creator"),
        base_url=_required_string(data["base_url"], "base_url").rstrip("/"),
        index_path=_required_string(data["index_path"], "index_path"),
        series_index_path=_required_string(data["series_index_path"], "series_index_path"),
        scp001_path=_required_string(data["scp001_path"], "scp001_path"),
        cache_dir=_workspace_path(workspace, "cache_dir", data["cache_dir"]),
        manifest_dir=_workspace_path(workspace, "manifest_dir", data["manifest_dir"]),
        processed_dir=_workspace_path(workspace, "processed_dir", data["processed_dir"]),
        output_dir=_workspace_path(workspace, "output_dir", data["output_dir"]),
        request_delay_seconds=_non_negative_number(
            data["request_delay_seconds"], "request_delay_seconds"
        ),
        request_timeout_seconds=_positive_number(
            data.get("request_timeout_seconds", 30),
            "request_timeout_seconds",
        ),
        retry_count=_minimum_integer(data["retry_count"], "retry_count", 1),
        asset_timeout_seconds=_positive_number(
            data.get("asset_timeout_seconds", data.get("request_timeout_seconds", 30)),
            "asset_timeout_seconds",
        ),
        asset_retry_count=_minimum_integer(
            data.get("asset_retry_count", data["retry_count"]),
            "asset_retry_count",
            1,
        ),
        include_scp001_proposals=_optional_bool(
            data.get("include_scp001_proposals", False),
            "include_scp001_proposals",
        ),
        volumes=volumes,
        index_mode=_optional_index_mode(data.get("index_mode", "tales")),
        featured_archive_url=_optional_string(
            data.get("featured_archive_url"),
            "featured_archive_url",
        ),
        include_linked_appendices=_optional_bool(
            data.get("include_linked_appendices", True),
            "include_linked_appendices",
        ),
        featured_title_index_paths=_optional_string_tuple(
            data.get("featured_title_index_paths"),
            "featured_title_index_paths",
        ),
        front_matter_pages=_load_configured_pages(
            data.get("front_matter_pages"),
            "front_matter_pages",
        ),
        explicit_linked_appendices=_load_explicit_linked_appendices(
            data.get("explicit_linked_appendices", {}),
            "explicit_linked_appendices",
            _required_string(data["base_url"], "base_url").rstrip("/"),
        ),
        page_tab_includes=_load_string_tuple_mapping(
            data.get("page_tab_includes", {}),
            "page_tab_includes",
        ),
        page_overrides=_load_page_overrides(
            data.get("page_overrides", {}),
            "page_overrides",
            _required_string(data["base_url"], "base_url").rstrip("/"),
        ),
        page_fallbacks=_load_page_fallbacks(
            data.get("page_fallbacks", {}),
            "page_fallbacks",
            workspace,
        ),
        appendix=_load_appendix(
            data.get("appendix"),
            "appendix",
            _required_string(data["base_url"], "base_url").rstrip("/"),
        ),
    )


def _load_volumes(value: Any) -> dict[str, VolumeSpec]:
    volumes: dict[str, VolumeSpec] = {}
    for key, volume_data in _mapping(value, "volumes").items():
        volume_key = str(key)
        volume = _mapping(volume_data, f"volume {volume_key}")
        missing = sorted(REQUIRED_VOLUME_KEYS - set(volume))
        if missing:
            raise ValueError(
                f"Volume {volume_key} missing required keys: {', '.join(missing)}"
            )
        start = _positive_integer(volume["start"], f"Volume {volume_key} start")
        end = _positive_integer(volume["end"], f"Volume {volume_key} end")
        if start > end:
            raise ValueError(f"Volume {volume_key} start must be <= end")

        volumes[volume_key] = VolumeSpec(
            key=volume_key,
            start=start,
            end=end,
            title=_required_string(volume["title"], f"Volume {volume_key} title"),
            output_slug=_required_string(
                volume["output_slug"], f"Volume {volume_key} output_slug"
            ),
        )

    if not volumes:
        raise ValueError("Config must define at least one volume")
    return volumes


def _load_configured_pages(value: Any, name: str) -> tuple[ConfiguredPage, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list of page mappings")

    pages: list[ConfiguredPage] = []
    for index, item in enumerate(value):
        page = _mapping(item, f"{name}[{index}]")
        title = _required_string(page.get("title"), f"{name}[{index}].title")
        url = _required_string(page.get("url"), f"{name}[{index}].url")
        slug = _optional_string(page.get("slug"), f"{name}[{index}].slug") or slug_from_url(url)
        role = _optional_string(page.get("role"), f"{name}[{index}].role") or "front-matter"
        epub_background_url = _optional_string(
            page.get("epub_background_url"),
            f"{name}[{index}].epub_background_url",
        )
        unwrap_single_included_tab = _optional_bool(
            page.get("unwrap_single_included_tab", False),
            f"{name}[{index}].unwrap_single_included_tab",
        )
        pages.append(
            ConfiguredPage(
                title=title,
                url=url,
                slug=slug,
                role=role,
                epub_background_url=epub_background_url,
                unwrap_single_included_tab=unwrap_single_included_tab,
            )
        )
    return tuple(pages)


def _load_explicit_linked_appendices(
    value: Any,
    name: str,
    base_url: str,
) -> dict[str, tuple[ConfiguredLink, ...]]:
    if value is None:
        return {}
    mapping = _mapping(value, name)
    appendices: dict[str, tuple[ConfiguredLink, ...]] = {}
    for source_slug, raw_links in mapping.items():
        source_key = _required_string(str(source_slug), f"{name} key").strip().lower()
        if not isinstance(raw_links, list):
            raise ValueError(f"{name}.{source_key} must be a list of link mappings")
        links: list[ConfiguredLink] = []
        for index, raw_link in enumerate(raw_links):
            link = _mapping(raw_link, f"{name}.{source_key}[{index}]")
            title = _required_string(link.get("title"), f"{name}.{source_key}[{index}].title")
            raw_url = _required_string(link.get("url"), f"{name}.{source_key}[{index}].url")
            url = normalize_url(base_url, raw_url)
            slug = _optional_string(link.get("slug"), f"{name}.{source_key}[{index}].slug") or slug_from_url(url)
            links.append(ConfiguredLink(title=title, url=url, slug=slug))
        appendices[source_key] = tuple(links)
    return appendices


def _load_string_tuple_mapping(value: Any, name: str) -> dict[str, tuple[str, ...]]:
    if value is None:
        return {}
    mapping = _mapping(value, name)
    result: dict[str, tuple[str, ...]] = {}
    for key, raw_values in mapping.items():
        result[_required_string(str(key), f"{name} key").strip().lower()] = _optional_string_tuple(
            raw_values,
            f"{name}.{key}",
        )
    return result


def _load_page_overrides(
    value: Any,
    name: str,
    base_url: str,
) -> dict[str, PageOverride]:
    if value is None:
        return {}

    overrides: dict[str, PageOverride] = {}
    for raw_slug, raw_override in _mapping(value, name).items():
        slug = _required_string(raw_slug, f"{name} key").strip().lower()
        if slug in overrides:
            raise ValueError(f"{name} contains duplicate key after normalization: {slug}")
        override_name = f"{name}.{slug}"
        override = _mapping(raw_override, override_name)
        _reject_unknown_keys(
            override,
            {
                "remove_terminal_navigation",
                "remove_leading_metadata",
                "remove_adult_content_warning",
                "remove_author_work_list",
                "layout_profile",
                "inline_documents",
            },
            override_name,
        )
        overrides[slug] = PageOverride(
            remove_terminal_navigation=_optional_bool(
                override.get("remove_terminal_navigation", False),
                f"{override_name}.remove_terminal_navigation",
            ),
            remove_leading_metadata=_optional_bool(
                override.get("remove_leading_metadata", False),
                f"{override_name}.remove_leading_metadata",
            ),
            remove_adult_content_warning=_optional_bool(
                override.get("remove_adult_content_warning", False),
                f"{override_name}.remove_adult_content_warning",
            ),
            remove_author_work_list=_optional_bool(
                override.get("remove_author_work_list", False),
                f"{override_name}.remove_author_work_list",
            ),
            layout_profile=_optional_string(
                override.get("layout_profile"),
                f"{override_name}.layout_profile",
            ),
            inline_documents=_load_inline_documents(
                override.get("inline_documents"),
                f"{override_name}.inline_documents",
                base_url,
            ),
        )
    return overrides


def _absolute_http_url(value: Any, name: str) -> str:
    url = _required_string(value, name).strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must be an absolute HTTP(S) URL")
    return url


def _layout_signature(value: Any, name: str) -> str:
    signature = _required_string(value, name).strip().lower()
    if _SHA256_RE.fullmatch(signature) is None:
        raise ValueError(f"{name} must be a 64-character hexadecimal SHA-256")
    return signature


def _load_page_fallbacks(
    value: Any,
    name: str,
    workspace: Path,
) -> dict[str, PageFallback]:
    if value is None:
        return {}
    fallbacks: dict[str, PageFallback] = {}
    for raw_slug, raw_fallback in _mapping(value, name).items():
        slug = _required_string(raw_slug, f"{name} key").strip().lower()
        if slug in fallbacks:
            raise ValueError(f"{name} contains duplicate key after normalization: {slug}")
        fallback_name = f"{name}.{slug}"
        fallback = _mapping(raw_fallback, fallback_name)
        _reject_unknown_keys(
            fallback,
            {
                "source_url",
                "source_language",
                "translated_title",
                "snapshot_path",
                "layout_signature",
            },
            fallback_name,
        )
        snapshot_path = _workspace_path(
            workspace,
            f"{fallback_name}.snapshot_path",
            fallback.get("snapshot_path"),
        )
        if not snapshot_path.is_file():
            raise ValueError(f"{fallback_name}.snapshot_path does not exist: {snapshot_path}")
        fallbacks[slug] = PageFallback(
            source_url=_absolute_http_url(
                fallback.get("source_url"),
                f"{fallback_name}.source_url",
            ),
            source_language=_required_string(
                fallback.get("source_language"),
                f"{fallback_name}.source_language",
            ).strip(),
            translated_title=_required_string(
                fallback.get("translated_title"),
                f"{fallback_name}.translated_title",
            ).strip(),
            snapshot_path=snapshot_path,
            layout_signature=_layout_signature(
                fallback.get("layout_signature"),
                f"{fallback_name}.layout_signature",
            ),
        )
    return fallbacks


def _load_inline_documents(
    value: Any,
    name: str,
    base_url: str,
) -> tuple[InlineDocumentSpec, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list of inline document mappings")

    documents: list[InlineDocumentSpec] = []
    for index, raw_document in enumerate(value):
        document_name = f"{name}[{index}]"
        document = _mapping(raw_document, document_name)
        _reject_unknown_keys(
            document,
            {"title", "url", "slug", "position", "anchor_text"},
            document_name,
        )
        title = _required_string(document.get("title"), f"{document_name}.title")
        raw_url = _required_string(document.get("url"), f"{document_name}.url")
        url = normalize_url(base_url, raw_url)
        slug = _optional_string(document.get("slug"), f"{document_name}.slug") or slug_from_url(url)
        position = _inline_document_position(document.get("position"), f"{document_name}.position")
        raw_anchor_text = document.get("anchor_text")
        if position in {"after_text", "before_text"} and (
            raw_anchor_text is None
            or isinstance(raw_anchor_text, str) and not raw_anchor_text.strip()
        ):
            raise ValueError(f"{document_name}.anchor_text is required for position '{position}'")
        anchor_text = _optional_string(raw_anchor_text, f"{document_name}.anchor_text")
        documents.append(
            InlineDocumentSpec(
                title=title,
                url=url,
                slug=slug,
                position=position,
                anchor_text=anchor_text,
            )
        )
    return tuple(documents)


def _load_appendix(value: Any, name: str, base_url: str) -> AppendixSpec | None:
    if value is None:
        return None

    appendix = _mapping(value, name)
    title = _required_string(appendix.get("title"), f"{name}.title")
    slug = _required_string(appendix.get("slug"), f"{name}.slug").strip().lower()
    raw_sections = appendix.get("sections")
    if not isinstance(raw_sections, list):
        raise ValueError(f"{name}.sections must be a list of section mappings")
    if not raw_sections:
        raise ValueError(f"{name}.sections must define at least one section")

    sections: list[AppendixSection] = []
    for index, raw_section in enumerate(raw_sections):
        section_name = f"{name}.sections[{index}]"
        section = _mapping(raw_section, section_name)
        section_title = _required_string(section.get("title"), f"{section_name}.title")
        raw_url = _required_string(section.get("url"), f"{section_name}.url")
        url = normalize_url(base_url, raw_url)
        section_slug = _optional_string(section.get("slug"), f"{section_name}.slug") or slug_from_url(url)
        mode = _optional_appendix_mode(section.get("mode", "page"), f"{section_name}.mode")
        include_tabs = _optional_string_tuple(section.get("include_tabs"), f"{section_name}.include_tabs")
        unwrap_single_tab = _optional_bool(
            section.get("unwrap_single_tab", False),
            f"{section_name}.unwrap_single_tab",
        )
        sections.append(
            AppendixSection(
                title=section_title,
                url=url,
                slug=section_slug,
                mode=mode,
                include_tabs=include_tabs,
                unwrap_single_tab=unwrap_single_tab,
            )
        )

    return AppendixSpec(title=title, slug=slug, sections=tuple(sections))


def _workspace_path(workspace: Path, key: str, value: Any) -> Path:
    raw_path = Path(_required_string(value, key))
    if raw_path.is_absolute() or raw_path.drive:
        raise ValueError(f"{key} must be a relative path inside the workspace")

    workspace = workspace.resolve()
    resolved = (workspace / raw_path).resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError:
        raise ValueError(f"{key} must stay inside the workspace") from None
    return resolved


def _required_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isfinite(value) and value.is_integer():
            return int(value)
        raise ValueError(f"{name} must be an integer")
    if isinstance(value, str):
        try:
            return int(value.strip(), 10)
        except ValueError:
            raise ValueError(f"{name} must be an integer") from None
    try:
        converted = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer") from None
    if converted != value:
        raise ValueError(f"{name} must be an integer")
    return converted


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number") from None
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _non_negative_number(value: Any, name: str) -> float:
    number = _number(value, name)
    if number < 0:
        raise ValueError(f"{name} must be non-negative")
    return number


def _positive_number(value: Any, name: str) -> float:
    number = _number(value, name)
    if number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


def _minimum_integer(value: Any, name: str, minimum: int) -> int:
    integer = _integer(value, name)
    if integer < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return integer


def _positive_integer(value: Any, name: str) -> int:
    integer = _integer(value, name)
    if integer <= 0:
        raise ValueError(f"{name} must be positive")
    return integer


def _optional_bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    raise ValueError(f"{name} must be a boolean")


def _optional_string(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _optional_string_tuple(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (_required_string(value, name).strip(),)
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a string or list of strings")
    values: list[str] = []
    for index, item in enumerate(value):
        values.append(_required_string(item, f"{name}[{index}]").strip())
    return tuple(values)


def _optional_index_mode(value: Any) -> str:
    mode = _required_string(value, "index_mode")
    if mode not in {"tales", "featured-scp-archive"}:
        raise ValueError("index_mode must be 'tales' or 'featured-scp-archive'")
    return mode


def _optional_appendix_mode(value: Any, name: str) -> str:
    mode = _required_string(value, name)
    if mode not in {"page", "facility-links", "tabs-as-pages"}:
        raise ValueError(
            f"{name} must be 'page', 'facility-links', or 'tabs-as-pages'"
        )
    return mode


def _inline_document_position(value: Any, name: str) -> str:
    position = _required_string(value, name)
    if position not in {"after_text", "before_text", "append"}:
        raise ValueError(f"{name} must be 'after_text', 'before_text', or 'append'")
    return position


def _reject_unknown_keys(
    value: dict[str, Any],
    allowed_keys: set[str],
    name: str,
) -> None:
    unknown_keys = sorted(str(key) for key in value.keys() if key not in allowed_keys)
    if unknown_keys:
        raise ValueError(f"{name} contains unknown keys: {', '.join(unknown_keys)}")


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    return value
