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
        (["objects", "--help"], 0),
        (["items", "--help"], 0),
        (["get", "--help"], 0),
        (["put", "--help"], 0),
        (["scripts", "--help"], 0),
        (["scripts", "start", "--help"], 0),
        (["tail", "--help"], 0),
    ],
)
def test_cli_help(args, expected):
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == expected, result.output
    assert "ridercli" in result.output
