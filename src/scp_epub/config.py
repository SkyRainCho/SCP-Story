from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import AppConfig, VolumeSpec


REQUIRED_TOP_LEVEL = {
    "series_id",
    "title",
    "language",
    "creator",
    "base_url",
    "index_path",
    "scp001_path",
    "cache_dir",
    "manifest_dir",
    "processed_dir",
    "output_dir",
    "request_delay_seconds",
    "retry_count",
    "volumes",
}


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).resolve()
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    missing = sorted(REQUIRED_TOP_LEVEL - set(data))
    if missing:
        raise ValueError(f"Config missing required keys: {', '.join(missing)}")

    volumes = {
        key: VolumeSpec(
            key=key,
            start=int(value["start"]),
            end=int(value["end"]),
            title=str(value["title"]),
            output_slug=str(value["output_slug"]),
        )
        for key, value in _mapping(data["volumes"]).items()
    }
    if not volumes:
        raise ValueError("Config must define at least one volume")

    workspace = config_path.parent.parent if config_path.parent.name == "config" else config_path.parent

    return AppConfig(
        workspace=workspace,
        series_id=str(data["series_id"]),
        title=str(data["title"]),
        language=str(data["language"]),
        creator=str(data["creator"]),
        base_url=str(data["base_url"]).rstrip("/"),
        index_path=str(data["index_path"]),
        scp001_path=str(data["scp001_path"]),
        cache_dir=workspace / str(data["cache_dir"]),
        manifest_dir=workspace / str(data["manifest_dir"]),
        processed_dir=workspace / str(data["processed_dir"]),
        output_dir=workspace / str(data["output_dir"]),
        request_delay_seconds=float(data["request_delay_seconds"]),
        retry_count=int(data["retry_count"]),
        volumes=volumes,
    )


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("volumes must be a mapping")
    return value
