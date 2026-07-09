from __future__ import annotations

import math
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
        scp001_path=_required_string(data["scp001_path"], "scp001_path"),
        cache_dir=_workspace_path(workspace, "cache_dir", data["cache_dir"]),
        manifest_dir=_workspace_path(workspace, "manifest_dir", data["manifest_dir"]),
        processed_dir=_workspace_path(workspace, "processed_dir", data["processed_dir"]),
        output_dir=_workspace_path(workspace, "output_dir", data["output_dir"]),
        request_delay_seconds=_non_negative_number(
            data["request_delay_seconds"], "request_delay_seconds"
        ),
        retry_count=_minimum_integer(data["retry_count"], "retry_count", 1),
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


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    return value
