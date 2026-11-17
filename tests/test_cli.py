"""Smoke tests for the click CLI surface (no viewer needed)."""

import pytest
from click.testing import CliRunner

from ridercli.cli import cli


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ([], 2),  # bare invocation: usage error (standard click group behaviour)
        (["--help"], 0),
        (["probe", "--help"], 0),
        (["status", "--help"], 0),
    ],
)
def test_cli_help(args, expected):
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == expected, result.output
    assert "ridercli" in result.output
