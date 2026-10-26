"""The command lines parse: every subcommand is wired and the shared report commands are on both."""

import pytest

from mobiletester.android import cli as adt


@pytest.mark.parametrize("argv", [
    ["report", "check", "RUN"],
    ["report", "confirm", "RUN", "B1", "--result", "reproduced", "--by", "Ihor"],
    ["issues", "list", "--package", "com.example"],
    ["issues", "set", "K-1", "--package", "com.example", "--status", "fixed"],
    ["tap", "--text", "OK", "--fast"],
    ["--fast", "app", "reset", "com.example", "--level", "clear-data"],
    ["session", "start", "--package", "com.example", "--mode", "explore", "--record"],
    ["open", "https://example.com/item/42", "--package", "com.example", "--cold", "--no-observe"],
    ["report", "telemetry", "RUN", "--until", "23:57:19"],
    ["report", "decision", "RUN", "consent_banners", "reject_non_essential", "--why", "cookie banner"],
    ["report", "set", "RUN", "install_source", "Play Store"],
    ["report", "add", "RUN", "setup_steps_fast", "clear data"],
])
def test_adt_parses(argv):
    args = adt.build_parser().parse_args(argv)
    assert args.cmd == argv[1] if argv[0].startswith("-") else args.cmd == argv[0]


def test_adt_issues_default_to_the_project_folder():
    assert adt.build_parser().parse_args(["issues", "list", "--package", "p"]).config_dir == ".mobile-tester"


@pytest.mark.parametrize("argv", [
    ["report", "build", "RUN"],
    ["issues", "sync", "RUN", "--package", "com.github.aint.Habits"],
    ["tap", "--xy", "200.5", "300"],
    ["--fast", "app", "reset", "com.github.aint.Habits", "--level", "clear-data"],
    ["session", "start", "--package", "com.github.aint.Habits", "--mode", "explore", "--record", "--log"],
    ["runner", "start"],
    ["type", "Run 5k", "--submit"],
    ["log", "start", "--out", "x.log", "--package", "com.github.aint.Habits"],
    ["open", "habits://today", "--no-observe"],
    ["report", "telemetry", "RUN"],
])
def test_idt_parses(argv):
    from mobiletester.ios import cli as idt

    args = idt.build_parser().parse_args(argv)
    assert args.cmd == (argv[1] if argv[0].startswith("-") else argv[0])
