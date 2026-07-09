from pathlib import Path

import pytest

from scp_epub.config import load_config


VALID_CONFIG = """
series_id: scp-series-1
title: Test Series
language: zh-CN
creator: Test Creator
base_url: https://example.test
index_path: /index
scp001_path: /scp-001
cache_dir: {cache_dir}
manifest_dir: {manifest_dir}
processed_dir: {processed_dir}
output_dir: {output_dir}
request_delay_seconds: {request_delay_seconds}
retry_count: {retry_count}
volumes:
  "001-099":
    start: {start}
    end: {end}
    title: Volume Title
    output_slug: volume-slug
"""


def write_config(config_path: Path, **overrides: str) -> None:
    values = {
        "cache_dir": "data/raw",
        "manifest_dir": "data/manifests",
        "processed_dir": "data/processed",
        "output_dir": "output",
        "request_delay_seconds": "0.1",
        "retry_count": "2",
        "start": "1",
        "end": "99",
    }
    values.update(overrides)
    config_path.write_text(VALID_CONFIG.format(**values), encoding="utf-8")


def test_load_config_builds_absolute_urls_and_paths(tmp_path: Path):
    config_path = tmp_path / "series.yaml"
    write_config(config_path)

    config = load_config(config_path)

    assert config.index_url == "https://example.test/index"
    assert config.scp001_url == "https://example.test/scp-001"
    assert config.cache_dir == tmp_path / "data/raw"
    assert config.manifest_dir == tmp_path / "data/manifests"
    assert config.processed_dir == tmp_path / "data/processed"
    assert config.output_dir == tmp_path / "output"
    assert config.volumes["001-099"].start == 1
    assert config.workspace == tmp_path


def test_load_config_under_config_dir_uses_parent_workspace(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "series.yaml"
    write_config(config_path)

    config = load_config(config_path)

    assert config.workspace == tmp_path
    assert config.cache_dir == tmp_path / "data/raw"


def test_load_config_rejects_missing_volume(tmp_path: Path):
    config_path = tmp_path / "series.yaml"
    config_path.write_text("series_id: bad\n", encoding="utf-8")

    try:
        load_config(config_path)
    except ValueError as exc:
        assert "volumes" in str(exc)
    else:
        raise AssertionError("expected ValueError")


@pytest.mark.parametrize("yaml_text", ["42\n", "- series_id\n"])
def test_load_config_rejects_non_mapping_top_level(tmp_path: Path, yaml_text: str):
    config_path = tmp_path / "series.yaml"
    config_path.write_text(yaml_text, encoding="utf-8")

    with pytest.raises(ValueError, match="config must be a mapping"):
        load_config(config_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cache_dir", "../raw"),
        ("manifest_dir", "{absolute}"),
    ],
)
def test_load_config_rejects_paths_outside_workspace(tmp_path: Path, field: str, value: str):
    config_path = tmp_path / "series.yaml"
    if value == "{absolute}":
        value = (tmp_path.parent / "manifests").resolve().as_posix()
    write_config(config_path, **{field: value})

    with pytest.raises(ValueError, match=field):
        load_config(config_path)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("retry_count", "many", "retry_count must be an integer"),
        (
            "request_delay_seconds",
            "soon",
            "request_delay_seconds must be a number",
        ),
    ],
)
def test_load_config_rejects_invalid_top_level_numbers(
    tmp_path: Path, field: str, value: str, expected: str
):
    config_path = tmp_path / "series.yaml"
    write_config(config_path, **{field: value})

    with pytest.raises(ValueError, match=expected):
        load_config(config_path)


@pytest.mark.parametrize(
    ("volume_yaml", "expected"),
    [
        (
            """
volumes:
  "001-099": malformed
""",
            "001-099",
        ),
        (
            """
volumes:
  "001-099":
    end: 99
    title: Volume Title
    output_slug: volume-slug
""",
            "001-099.*start",
        ),
    ],
)
def test_load_config_rejects_malformed_volume_entries(
    tmp_path: Path, volume_yaml: str, expected: str
):
    config_path = tmp_path / "series.yaml"
    config_path.write_text(
        """
series_id: scp-series-1
title: Test Series
language: zh-CN
creator: Test Creator
base_url: https://example.test
index_path: /index
scp001_path: /scp-001
cache_dir: data/raw
manifest_dir: data/manifests
processed_dir: data/processed
output_dir: output
request_delay_seconds: 0.1
retry_count: 2
"""
        + volume_yaml,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=expected):
        load_config(config_path)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("start", "first", "Volume 001-099 start must be an integer"),
        ("end", "last", "Volume 001-099 end must be an integer"),
    ],
)
def test_load_config_rejects_invalid_volume_numbers(
    tmp_path: Path, field: str, value: str, expected: str
):
    config_path = tmp_path / "series.yaml"
    write_config(config_path, **{field: value})

    with pytest.raises(ValueError, match=expected):
        load_config(config_path)
