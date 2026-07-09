from scp_epub.cli import build_parser, main


def test_parser_exposes_expected_commands():
    parser = build_parser()
    commands = [
        parser.parse_args([command]).command
        for command in ("build", "clean", "fetch", "index")
    ]
    assert commands == ["build", "clean", "fetch", "index"]


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
