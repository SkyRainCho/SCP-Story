from scp_epub.cli import build_parser, main


def test_parser_exposes_expected_commands():
    parser = build_parser()
    choices = parser._subparsers._group_actions[0].choices
    assert sorted(choices) == ["build", "clean", "fetch", "index"]


def test_help_returns_success(capsys):
    result = main(["--help"])
    captured = capsys.readouterr()
    assert result == 0
    assert "SCP EPUB pipeline" in captured.out
