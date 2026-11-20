"""Smoke tests for the click CLI surface (no viewer needed)."""

import pytest
from click.testing import CliRunner

from slsync.cli import cli


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
        (["commands", "list", "--help"], 0),
        (["commands", "run", "--help"], 0),
    ],
)
def test_cli_help(args, expected):
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == expected, result.output
    assert "slsync" in result.output


@pytest.mark.parametrize(
    ("candidate", "wanted", "expected"),
    [
        ("foo", "foo", True),
        ("FOO", "foo", True),  # case-insensitive
        ("foo 1", "foo", True),  # sim duplicate rename
        ("foo 42", "foo", True),
        ("foo 1x", "foo", False),
        ("foobar", "foo", False),  # longer prefix, not a rename
        ("foo_1", "foo", False),
        ("bar", "foo", False),
        ("", "foo", False),
        ("foo", "", False),
    ],
)
def test_is_sim_rename(candidate, wanted, expected):
    from slsync.cli import _is_sim_rename

    assert _is_sim_rename(candidate, wanted) is expected
