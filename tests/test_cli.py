import pytest

from scp_epub.cli import build_parser, main


def test_parser_exposes_expected_commands():
    parser = build_parser()
    commands = [
        parser.parse_args([command]).command
        for command in (
            "build",
            "clean",
            "fetch",
            "index",
            "manifest",
            "scan-linked-appendices",
        )
    ]
    assert commands == [
        "build",
        "clean",
        "fetch",
        "index",
        "manifest",
        "scan-linked-appendices",
    ]


def test_parser_accepts_config_after_subcommand():
    parser = build_parser()
    args = parser.parse_args(
        ["index", "--config", "config/custom.yaml", "--volume", "010-020"]
    )
    assert args.command == "index"
    assert args.config == "config/custom.yaml"
    assert args.volume == "010-020"


def test_parser_accepts_kindle_only_for_build():
    parser = build_parser()

    args = parser.parse_args(["build", "--volume", "featured", "--kindle"])

    assert args.command == "build"
    assert args.volume == "featured"
    assert args.kindle is True
    with pytest.raises(SystemExit):
        parser.parse_args(["fetch", "--kindle"])


def test_help_returns_success(capsys):
    result = main(["--help"])
    captured = capsys.readouterr()
    assert result == 0
    assert "SCP EPUB pipeline" in captured.out


def test_short_help_returns_success(capsys):
    result = main(("-h",))
    captured = capsys.readouterr()
    assert result == 0
    assert "SCP EPUB pipeline" in captured.out


def test_manifest_command_invokes_pipeline_with_config_and_volume(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_load_config(path):
        calls.append(("load_config", path))
        return "config"

    def fake_build_manifest(config, volume):
        calls.append(("build_manifest", config, volume))
        return [object(), object()]

    monkeypatch.setattr("scp_epub.pipeline.load_config", fake_load_config)
    monkeypatch.setattr("scp_epub.pipeline.build_manifest", fake_build_manifest)
    monkeypatch.setattr(
        "scp_epub.pipeline.manifest_path_for_volume",
        lambda _config, _volume: tmp_path / "manifest.json",
    )

    result = main(["manifest", "--config", "config/custom.yaml", "--volume", "001-099"])

    captured = capsys.readouterr()
    assert result == 0
    assert calls == [
        ("load_config", "config/custom.yaml"),
        ("build_manifest", "config", "001-099"),
    ]
    assert "manifest.json" in captured.out
    assert "2 pages" in captured.out


def test_scan_linked_appendices_command_invokes_pipeline(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_load_config(path):
        calls.append(("load_config", path))
        return "config"

    def fake_scan(config, volume, *, force=False):
        calls.append(("scan_linked_appendices_for_volume", config, volume, force))
        return tmp_path / "linked-appendices.json"

    monkeypatch.setattr("scp_epub.pipeline.load_config", fake_load_config)
    monkeypatch.setattr(
        "scp_epub.pipeline.scan_linked_appendices_for_volume",
        fake_scan,
    )

    result = main(
        [
            "scan-linked-appendices",
            "--config",
            "config/custom.yaml",
            "--volume",
            "001-099",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert calls == [
        ("load_config", "config/custom.yaml"),
        ("scan_linked_appendices_for_volume", "config", "001-099", False),
    ]
    assert "linked-appendices.json" in captured.out


def test_build_command_passes_kindle_and_prints_both_outputs(
    monkeypatch, tmp_path, capsys
):
    calls = []
    epub_path = tmp_path / "output" / "epub" / "book-Kindle.epub"
    azw3_path = tmp_path / "output" / "azw3" / "book-Kindle.azw3"

    monkeypatch.setattr("scp_epub.pipeline.load_config", lambda _path: "config")

    def fake_build_volume(config, volume, *, force=False, kindle=False):
        calls.append((config, volume, force, kindle))
        return epub_path

    monkeypatch.setattr("scp_epub.pipeline.build_volume", fake_build_volume)
    monkeypatch.setattr(
        "scp_epub.pipeline.kindle_azw3_path_for_volume",
        lambda _config, _volume: azw3_path,
    )

    result = main(
        [
            "build",
            "--config",
            "config/featured-scp.yaml",
            "--volume",
            "featured",
            "--kindle",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert calls == [("config", "featured", False, True)]
    assert str(epub_path) in captured.out
    assert str(azw3_path) in captured.out
