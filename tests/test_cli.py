from scp_epub.cli import build_parser, main


def test_parser_exposes_expected_commands():
    parser = build_parser()
    commands = [
        parser.parse_args([command]).command
        for command in ("build", "clean", "fetch", "index", "manifest")
    ]
    assert commands == ["build", "clean", "fetch", "index", "manifest"]


def test_parser_accepts_config_after_subcommand():
    parser = build_parser()
    args = parser.parse_args(
        ["index", "--config", "config/custom.yaml", "--volume", "010-020"]
    )
    assert args.command == "index"
    assert args.config == "config/custom.yaml"
    assert args.volume == "010-020"


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
