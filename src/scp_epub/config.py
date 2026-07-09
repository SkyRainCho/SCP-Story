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


REQUIRED_VOLUME_KEYS = {"start", "end", "title", "output_slug"}


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).resolve()
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    missing = sorted(REQUIRED_TOP_LEVEL - set(data))
    if missing:
        raise ValueError(f"Config missing required keys: {', '.join(missing)}")

    volumes = _load_volumes(data["volumes"])

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
        cache_dir=_workspace_path(workspace, "cache_dir", data["cache_dir"]),
        manifest_dir=_workspace_path(workspace, "manifest_dir", data["manifest_dir"]),
        processed_dir=_workspace_path(workspace, "processed_dir", data["processed_dir"]),
        output_dir=_workspace_path(workspace, "output_dir", data["output_dir"]),
        request_delay_seconds=float(data["request_delay_seconds"]),
        retry_count=int(data["retry_count"]),
        volumes=volumes,
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
        volumes[volume_key] = VolumeSpec(
            key=volume_key,
            start=int(volume["start"]),
            end=int(volume["end"]),
            title=str(volume["title"]),
            output_slug=str(volume["output_slug"]),
        )

    if not volumes:
        raise ValueError("Config must define at least one volume")
    return volumes


def _workspace_path(workspace: Path, key: str, value: Any) -> Path:
    raw_path = Path(str(value))
    if raw_path.is_absolute() or raw_path.drive:
        raise ValueError(f"{key} must be a relative path inside the workspace")

    workspace = workspace.resolve()
    resolved = (workspace / raw_path).resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError:
        raise ValueError(f"{key} must stay inside the workspace") from None
    return resolved


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    return value
