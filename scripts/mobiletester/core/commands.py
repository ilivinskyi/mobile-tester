"""Commands that work the same on every platform: report, issues, and the helpers both CLIs share."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from . import lifecycle, report, ui
from .state import PROJECT_DIR

EXIT_OK, EXIT_USAGE, EXIT_DEVICE, EXIT_NOT_FOUND, EXIT_BLOCKED, EXIT_DECISION = 0, 2, 3, 4, 5, 6


class NotFound(Exception):
    pass


class Blocked(Exception):
    pass


class NeedsDecision(Exception):
    """The user (or the auto-mode default) has to choose how to continue."""


def parse_time(value: str) -> float:
    """Epoch seconds from an epoch number, an ISO timestamp (actions.jsonl) or HH:MM:SS today."""
    try:
        return float(value)
    except ValueError:
        pass
    if len(value) <= 8 and value.count(":") in (1, 2):
        today = datetime.now().strftime("%Y-%m-%d")
        return datetime.fromisoformat(f"{today}T{value}").timestamp()
    return datetime.fromisoformat(value).timestamp()


def report_after_session(run: Path, tool: str) -> None:
    """Build the report as soon as the session ends, so it exists whatever drove the session.

    The wrap-up (clips, known issues, confirmations) rebuilds it with `report build` afterwards.
    """
    problems = report.check(run)
    if problems:
        print(f"report not built yet, {len(problems)} problem(s) to fix first ({tool} report check {run}):")
        for problem in problems[:5]:
            print(f"  - {problem}")
        return
    print(f"report: {report.build(run)[0]}")


def _report_confirm(args) -> int:
    run = Path(args.dir)
    result = lifecycle.confirm_in_run(run, args.finding, result=args.result, by=args.by, tries=args.tries,
                                      note=args.note or "", device=args.device, build=args.build)
    f, entry = result["finding"], result["entry"]
    print(f"{f['id']}: {entry['result']} {entry['tries']} by {entry['by']}; manual now "
          f"{f['reproducibility']['manual']}, status {f['status']}")
    if (run / "index.html").exists():
        report.build(run)
        print("report rebuilt")
    return EXIT_OK


def cmd_issues(args) -> int:
    config = Path(args.config_dir)
    match args.issues_cmd:
        case "list":
            issues = lifecycle.load_registry(config, args.package)["issues"]
            shown = [i for i in issues if args.status in ("all", i["status"])]
            if args.json:
                print(json.dumps(shown, ensure_ascii=False, indent=1))
            elif not shown:
                print(f"no {args.status} known issues for {args.package}")
            for i in shown if not args.json else []:
                last = i["seen"][-1]
                print(f"{i['key']}  {i['status']:<9} {i.get('severity') or '-':<8} {i['title']}  "
                      f"(seen {len(i['seen'])}x, last {last['date']} build {last['build']}"
                      + (f", test {i['test_case']}" if i.get("test_case") else "") + ")")
        case "sync":
            result = lifecycle.sync_registry(Path(args.dir), config, args.package)
            added, seen = ", ".join(result["added"]) or "none", ", ".join(result["seen_again"]) or "none"
            print(f"added: {added}; seen again: {seen}")
        case "set":
            issue = lifecycle.set_issue(config, args.package, args.key, args.status, note=args.note or "",
                                        run=args.run or "", build=args.build or "")
            print(f"{issue['key']} is now {issue['status']}")
    return EXIT_OK


def cmd_report(args) -> int:
    if args.report_cmd == "confirm":
        return _report_confirm(args)
    run = Path(args.dir)
    problems = report.check(run)
    if args.report_cmd == "check" or problems:
        for p in problems:
            print(f"problem: {p}")
        if problems:
            return EXIT_USAGE
        print("report data ok")
        if args.report_cmd == "check":
            return EXIT_OK
    for path in report.build(run):
        print(f"wrote {path}")
    return EXIT_OK


def subparsers(parser: argparse.ArgumentParser, common: argparse.ArgumentParser, **kwargs):
    group = parser.add_subparsers(**kwargs)
    add = group.add_parser

    def add_with_globals(name, **kw):
        return add(name, parents=[common], **kw)

    group.add_parser = add_with_globals
    return group


def add_parsers(sub, common: argparse.ArgumentParser) -> None:
    """The report and issues commands, on the subcommand group of either CLI."""
    p = sub.add_parser("report", help="validate and render the standard report of a run folder")
    rep = subparsers(p, common, dest="report_cmd", required=True)
    for name in ("check", "build"):
        rp = rep.add_parser(name)
        rp.add_argument("dir")
    rp = rep.add_parser("confirm", help="record a person's reproduction attempt on a finding, then rebuild")
    rp.add_argument("dir")
    rp.add_argument("finding", help="finding id, e.g. B3")
    rp.add_argument("--result", required=True, choices=list(lifecycle.CONFIRM_RESULTS))
    rp.add_argument("--by", required=True, help="who tried it")
    rp.add_argument("--tries", help="succeeded/attempted, e.g. 2/2 (default 1/1 or 0/1)")
    rp.add_argument("--note")
    rp.add_argument("--device", help="default: the session's device")
    rp.add_argument("--build", help="default: the session's build")

    p = sub.add_parser("issues", help="the app's known-issues registry (.mobile-tester/apps/<package>/)")
    iss = subparsers(p, common, dest="issues_cmd", required=True)
    for name in ("list", "sync", "set"):
        ip = iss.add_parser(name)
        ip.add_argument("--package", required=True)
        ip.add_argument("--config-dir", default=PROJECT_DIR)
        if name == "list":
            ip.add_argument("--status", default="open", choices=["all", *lifecycle.ISSUE_STATUSES])
            ip.add_argument("--json", action="store_true")
        elif name == "sync":
            ip.add_argument("dir", help="run folder whose findings to register")
        else:
            ip.add_argument("key", help="e.g. K-3")
            ip.add_argument("--status", required=True, choices=list(lifecycle.ISSUE_STATUSES))
            ip.add_argument("--note")
            ip.add_argument("--run", help="run folder name the change comes from (retest)")
            ip.add_argument("--build")


def previous_elements(previous: dict | None, fingerprint: str) -> list[ui.Element] | None:
    """The last observation's elements when it showed the same screen, for listing only what changed."""
    if not previous or fingerprint in ("", "-") or previous.get("fingerprint") != fingerprint:
        return None
    return [ui.Element.from_dict(e) for e in previous.get("elements", [])]


def observe_after(args, changed: bool | None, mode: str | None) -> bool:
    """Whether an action prints the new screen itself, saving a separate observe call per step.

    Only when the screen visibly changed. Never in fast mode, and not in repro sessions: reading the UI tree
    turns on the accessibility layer, which repro runs keep off (they check with plain screenshots).
    `--observe` forces it, `--no-observe` turns it off.
    """
    if getattr(args, "observe", False):
        return True
    if getattr(args, "no_observe", False) or getattr(args, "fast", False) or mode == "repro":
        return False
    return changed is True


def inspect_target(snapshot: ui.Snapshot, args) -> ui.Element:
    """The element `inspect` is about: by index, or the best text or id match in the last observation."""
    if args.index is not None:
        return snapshot.find(args.index)
    found = ui.find_by_text(snapshot, args.text) if args.text else ui.find_by_id(snapshot, args.id)
    if not found:
        raise NotFound(f"no element matching {args.text or args.id!r} in the last observation")
    return found[0]


def add_inspect_parser(sub, tool: str, dump: str) -> None:
    p = sub.add_parser("inspect", help=f"the raw {dump} node behind an element of the last observe, with its parent "
                                       "and children: proof for a finding without reading the whole dump")
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument("--index", type=int, help=f"element index from the last `{tool} observe`")
    target.add_argument("--text", help="best match by label")
    target.add_argument("--id", help="by resource id / accessibility identifier")
