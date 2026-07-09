from pathlib import Path

from scp_epub.config import load_config


def test_load_config_builds_absolute_urls(tmp_path: Path):
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
volumes:
  "001-099":
    start: 1
    end: 99
    title: Volume Title
    output_slug: volume-slug
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.index_url == "https://example.test/index"
    assert config.scp001_url == "https://example.test/scp-001"
    assert config.volumes["001-099"].start == 1
    assert config.workspace == tmp_path


def test_load_config_rejects_missing_volume(tmp_path: Path):
    config_path = tmp_path / "series.yaml"
    config_path.write_text("series_id: bad\n", encoding="utf-8")

    try:
        load_config(config_path)
    except ValueError as exc:
        assert "volumes" in str(exc)
    else:
        raise AssertionError("expected ValueError")
