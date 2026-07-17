import re
from pathlib import Path

import pytest

from scp_epub.config import load_config


VALID_CONFIG = """
series_id: {series_id}
title: {title}
language: {language}
creator: {creator}
base_url: {base_url}
index_path: {index_path}
series_index_path: {series_index_path}
scp001_path: {scp001_path}
cache_dir: {cache_dir}
manifest_dir: {manifest_dir}
processed_dir: {processed_dir}
output_dir: {output_dir}
request_delay_seconds: {request_delay_seconds}
retry_count: {retry_count}
request_timeout_seconds: {request_timeout_seconds}
asset_timeout_seconds: {asset_timeout_seconds}
asset_retry_count: {asset_retry_count}
volumes:
  "001-099":
    start: {start}
    end: {end}
    title: {volume_title}
    output_slug: {output_slug}
"""


def write_config(config_path: Path, **overrides: str) -> None:
    values = {
        "series_id": "scp-series-1",
        "title": "Test Series",
        "language": "zh-CN",
        "creator": "Test Creator",
        "base_url": "https://example.test",
        "index_path": "/index",
        "series_index_path": "/series",
        "scp001_path": "/scp-001",
        "cache_dir": "data/raw",
        "manifest_dir": "data/manifests",
        "processed_dir": "data/processed",
        "output_dir": "output",
        "request_delay_seconds": "0.1",
        "retry_count": "2",
        "request_timeout_seconds": "30",
        "asset_timeout_seconds": "5",
        "asset_retry_count": "1",
        "start": "1",
        "end": "99",
        "volume_title": "Volume Title",
        "output_slug": "volume-slug",
    }
    values.update(overrides)
    config_path.write_text(VALID_CONFIG.format(**values), encoding="utf-8")


def write_config_with_appendix(config_path: Path, appendix_yaml: str) -> None:
    write_config(config_path)
    config_path.write_text(
        f"{config_path.read_text(encoding='utf-8')}\nappendix:\n{appendix_yaml}",
        encoding="utf-8",
    )


def test_load_config_builds_absolute_urls_and_paths(tmp_path: Path):
    config_path = tmp_path / "series.yaml"
    write_config(config_path)

    config = load_config(config_path)

    assert config.index_url == "https://example.test/index"
    assert config.series_index_url == "https://example.test/series"
    assert config.scp001_url == "https://example.test/scp-001"
    assert config.cache_dir == tmp_path / "data/raw"
    assert config.manifest_dir == tmp_path / "data/manifests"
    assert config.processed_dir == tmp_path / "data/processed"
    assert config.output_dir == tmp_path / "output"
    assert config.request_timeout_seconds == 30
    assert config.asset_timeout_seconds == 5
    assert config.asset_retry_count == 1
    assert config.volumes["001-099"].start == 1
    assert config.workspace == tmp_path
    assert config.appendix is None


def test_series_1_config_defines_all_volume_ranges():
    config = load_config(Path("config/series-1.yaml"))

    expected_keys = ["001-099"] + [
        f"{start:03d}-{start + 99:03d}" for start in range(100, 1000, 100)
    ]
    assert list(config.volumes) == expected_keys
    assert config.volumes["001-099"].start == 1
    assert config.volumes["900-999"].end == 999


def test_series_1_config_includes_scp001_proposals():
    config = load_config(Path("config/series-1.yaml"))

    assert config.include_scp001_proposals is True


def test_featured_scp_config_uses_archive_mode_and_title_indexes():
    config = load_config(Path("config/featured-scp.yaml"))

    assert config.index_mode == "featured-scp-archive"
    assert config.featured_archive_url == "https://scp-wiki.wikidot.com/featured-scp-archive"
    assert config.featured_title_index_paths == ("/scp-series-9", "/scp-series-10")
    assert config.include_linked_appendices is True
    assert [page.slug for page in config.front_matter_pages] == ["about-the-scp-foundation"]
    assert config.front_matter_pages[0].title == "关于SCP基金会"
    assert config.front_matter_pages[0].epub_background_url == (
        "https://scp-wiki.wdfiles.com/local--files/about-the-scp-foundation/bg-marble.png"
    )
    assert config.front_matter_pages[0].unwrap_single_included_tab is True
    assert config.page_tab_includes == {"about-the-scp-foundation": ("简介",)}
    assert [link.slug for link in config.explicit_linked_appendices["scp-5170"]] == [
        "scp-5170/offset/1",
        "scp-5170/offset/2",
        "scp-5170/offset/3",
    ]
    assert list(config.volumes) == ["featured"]


def test_featured_scp_config_declares_appendix_structure():
    config = load_config(Path("config/featured-scp.yaml"))

    assert config.appendix is not None
    assert config.appendix.title == "附录"
    assert [section.title for section in config.appendix.sections] == [
        "项目等级",
        "安保许可等级",
        "基金会设施",
        "基金会部门",
        "人事档案",
        "O5指挥部档案",
        "相关组织",
        "相关地点",
    ]
    sections_by_title = {section.title: section for section in config.appendix.sections}
    assert sections_by_title["安保许可等级"].mode == "page"
    assert sections_by_title["安保许可等级"].include_tabs == ("简介",)
    assert sections_by_title["安保许可等级"].unwrap_single_tab is True
    assert sections_by_title["基金会设施"].mode == "facility-links"
    assert sections_by_title["人事档案"].mode == "tabs-as-pages"
    assert sections_by_title["O5指挥部档案"].mode == "tabs-as-pages"


def test_load_config_rejects_empty_appendix_sections(tmp_path: Path):
    config_path = tmp_path / "series.yaml"
    write_config_with_appendix(
        config_path,
        """\
  title: Appendix
  slug: appendix
  sections: []
""",
    )

    with pytest.raises(
        ValueError,
        match=re.escape("appendix.sections must define at least one section"),
    ):
        load_config(config_path)


@pytest.mark.parametrize(
    ("appendix_yaml", "expected"),
    [
        ("  - invalid\n", "appendix must be a mapping"),
        (
            """\
  title: Appendix
  slug: appendix
  sections:
    - invalid
""",
            "appendix.sections[0] must be a mapping",
        ),
    ],
)
def test_load_config_rejects_invalid_appendix_mappings(
    tmp_path: Path, appendix_yaml: str, expected: str
):
    config_path = tmp_path / "series.yaml"
    write_config_with_appendix(config_path, appendix_yaml)

    with pytest.raises(ValueError, match=re.escape(expected)):
        load_config(config_path)


@pytest.mark.parametrize(
    ("section_setting", "expected"),
    [
        (
            "mode: grouped",
            "appendix.sections[0].mode must be 'page', 'facility-links', or 'tabs-as-pages'",
        ),
        (
            "include_tabs: false",
            "appendix.sections[0].include_tabs must be a string or list of strings",
        ),
        ("unwrap_single_tab: []", "appendix.sections[0].unwrap_single_tab must be a boolean"),
    ],
)
def test_load_config_rejects_invalid_appendix_section_options(
    tmp_path: Path, section_setting: str, expected: str
):
    config_path = tmp_path / "series.yaml"
    write_config_with_appendix(
        config_path,
        f"""\
  title: Appendix
  slug: appendix
  sections:
    - title: Reference
      url: /reference
      {section_setting}
""",
    )

    with pytest.raises(ValueError, match=re.escape(expected)):
        load_config(config_path)


def test_load_config_normalizes_appendix_section_url_and_derives_slug(tmp_path: Path):
    config_path = tmp_path / "series.yaml"
    write_config_with_appendix(
        config_path,
        """\
  title: Appendix
  slug: appendix
  sections:
    - title: Reference
      url: reference-page
""",
    )

    appendix = load_config(config_path).appendix

    assert appendix is not None
    assert appendix.sections[0].url == "https://example.test/reference-page"
    assert appendix.sections[0].slug == "reference-page"


@pytest.mark.parametrize(
    ("series_number", "first_key"),
    [
        (1, "001-099"),
        (2, "1000-1099"),
        (3, "2000-2099"),
        (4, "3000-3099"),
        (5, "4000-4099"),
        (6, "5000-5099"),
        (7, "6000-6099"),
        (8, "7000-7099"),
    ],
)
def test_series_configs_use_chinese_book_metadata_and_output_names(series_number: int, first_key: str):
    config = load_config(Path(f"config/series-{series_number}.yaml"))

    assert config.title == "SCP基金会档案：故事系列"
    assert config.creator == "SCP基金会"

    assert first_key in config.volumes
    for book_number, volume in enumerate(config.volumes.values(), start=1):
        assert volume.title == f"SCP基金会档案：故事系列 第{series_number}卷-第{book_number}册"
        assert volume.output_slug == f"SCP基金会档案-故事系列-第{series_number}卷-第{book_number}册"


def test_series_2_config_defines_all_volume_ranges():
    config = load_config(Path("config/series-2.yaml"))

    expected_keys = [f"{start}-{start + 99}" for start in range(1000, 2000, 100)]
    assert config.series_id == "scp-series-2"
    assert config.index_path == "/scp-series-2-tales-edition"
    assert config.series_index_path == "/scp-series-2"
    assert list(config.volumes) == expected_keys
    assert config.volumes["1000-1099"].start == 1000
    assert config.volumes["1900-1999"].end == 1999


@pytest.mark.parametrize(
    ("series_number", "start"),
    [
        (3, 2000),
        (4, 3000),
        (5, 4000),
        (6, 5000),
        (7, 6000),
        (8, 7000),
    ],
)
def test_later_series_configs_define_all_volume_ranges(series_number: int, start: int):
    config = load_config(Path(f"config/series-{series_number}.yaml"))

    expected_keys = [f"{value}-{value + 99}" for value in range(start, start + 1000, 100)]
    assert config.series_id == f"scp-series-{series_number}"
    assert config.index_path == f"/scp-series-{series_number}-tales-edition"
    assert config.series_index_path == f"/scp-series-{series_number}"
    assert list(config.volumes) == expected_keys
    assert config.volumes[f"{start}-{start + 99}"].start == start
    assert config.volumes[f"{start + 900}-{start + 999}"].end == start + 999


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
        ("cache_dir", "", "cache_dir must be a non-empty string"),
        ("title", '"   "', "title must be a non-empty string"),
    ],
)
def test_load_config_rejects_invalid_top_level_strings(
    tmp_path: Path, field: str, value: str, expected: str
):
    config_path = tmp_path / "series.yaml"
    write_config(config_path, **{field: value})

    with pytest.raises(ValueError, match=expected):
        load_config(config_path)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("retry_count", "many", "retry_count must be an integer"),
        ("retry_count", "2.9", "retry_count must be an integer"),
        ("retry_count", '"2.9"', "retry_count must be an integer"),
        ("retry_count", "true", "retry_count must be an integer"),
        ("retry_count", "0", "retry_count must be at least 1"),
        ("asset_retry_count", "none", "asset_retry_count must be an integer"),
        ("asset_retry_count", "0", "asset_retry_count must be at least 1"),
        (
            "request_delay_seconds",
            "soon",
            "request_delay_seconds must be a number",
        ),
        (
            "request_delay_seconds",
            "-0.1",
            "request_delay_seconds must be non-negative",
        ),
        (
            "request_timeout_seconds",
            "0",
            "request_timeout_seconds must be positive",
        ),
        (
            "asset_timeout_seconds",
            "-1",
            "asset_timeout_seconds must be positive",
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
series_index_path: /series
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
        ("start", "1.9", "Volume 001-099 start must be an integer"),
        ("end", "last", "Volume 001-099 end must be an integer"),
        ("start", "0", "Volume 001-099 start must be positive"),
        ("end", "-1", "Volume 001-099 end must be positive"),
    ],
)
def test_load_config_rejects_invalid_volume_numbers(
    tmp_path: Path, field: str, value: str, expected: str
):
    config_path = tmp_path / "series.yaml"
    write_config(config_path, **{field: value})

    with pytest.raises(ValueError, match=expected):
        load_config(config_path)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("volume_title", "", "Volume 001-099 title must be a non-empty string"),
        (
            "output_slug",
            '""',
            "Volume 001-099 output_slug must be a non-empty string",
        ),
    ],
)
def test_load_config_rejects_invalid_volume_strings(
    tmp_path: Path, field: str, value: str, expected: str
):
    config_path = tmp_path / "series.yaml"
    write_config(config_path, **{field: value})

    with pytest.raises(ValueError, match=expected):
        load_config(config_path)


def test_load_config_rejects_reversed_volume_range(tmp_path: Path):
    config_path = tmp_path / "series.yaml"
    write_config(config_path, start="100", end="99")

    with pytest.raises(ValueError, match="Volume 001-099 start must be <= end"):
        load_config(config_path)
