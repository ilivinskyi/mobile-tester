"""Commands that work the same on every platform: report, issues, and the helpers both CLIs share."""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path

from . import (
    contrast,
    control,
    dashboard,
    devices,
    diff,
    findings,
    inputs,
    lifecycle,
    project,
    report,
    screens,
    session,
    state,
    telemetry,
    ui,
)
from .proc import detached_kwargs, is_alive, terminate
from .state import PROJECT_DIR

EXIT_OK, EXIT_USAGE, EXIT_DEVICE, EXIT_NOT_FOUND, EXIT_BLOCKED, EXIT_DECISION = 0, 2, 3, 4, 5, 6


class NotFound(Exception):
    pass


class Blocked(Exception):
    pass


class NeedsDecision(Exception):
    """The user (or the autopilot default) has to choose how to continue."""


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


def cmd_screens(args) -> int:
    """`screens RUN`: screens visited, controls never tried on each, taps that changed nothing."""
    print("\n".join(screens.lines(screens.inventory(Path(args.dir)))))
    return EXIT_OK


def cmd_report(args) -> int:
    if args.report_cmd == "confirm":
        return _report_confirm(args)
    if args.report_cmd in ("set", "add", "result"):
        return _report_fields(args)
    if args.report_cmd == "diff":
        print("\n".join(diff.compare(Path(args.dir), Path(args.other))))
        return EXIT_OK
    if args.report_cmd == "telemetry":
        return _report_telemetry(args)
    if args.report_cmd == "decision":
        entry = findings.record_decision(Path(args.dir), args.key, args.value, args.why or "")
        print(f"decision {entry['key']} = {entry['value']} logged at {entry['time']}")
        return EXIT_OK
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


def cmd_finding(args) -> int:
    run = Path(args.dir)
    values = {k: getattr(args, k, None) for k in (*findings.SCALAR_FIELDS, *findings.LIST_FIELDS, "automated",
                                                  "manual", "evidence", "clear_evidence")}
    try:
        match args.finding_cmd:
            case "add":
                problems = findings.add(run, args.id, values)
            case "update":
                problems = findings.update(run, args.id, values)
            case _:
                problems = findings.retract(run, args.id, args.reason)
    except findings.FindingError as exc:
        print(f"error: {exc}")
        return EXIT_USAGE
    print(f"{args.finding_cmd}: {args.id} saved in {run / 'findings.json'}")
    for p in problems:
        print(f"problem: {p}")
    if problems:
        print(f"fix with `finding update {run} {args.id} ...`; the report check fails until then")
        return EXIT_USAGE
    return EXIT_OK


def _report_fields(args) -> int:
    run = Path(args.dir)
    try:
        if args.report_cmd == "set":
            findings.session_set(run, args.field, args.value)
        elif args.report_cmd == "result":
            entry = findings.record_result(run, args.case, args.result, step=args.step or "", issue=args.issue or "",
                                           finding=args.finding or "", note=args.note or "")
            print(f"test result: {entry['case']}" + (f" step {entry['step']}" if entry.get("step") else "")
                  + f" = {entry['result']}")
            return EXIT_OK
        else:
            findings.session_add(run, args.field, args.values)
    except (findings.FindingError, ValueError) as exc:
        print(f"error: {exc}")
        return EXIT_USAGE
    print(f"session.json: {args.field} updated")
    return EXIT_OK


def _report_telemetry(args) -> int:
    run = Path(args.dir)
    transcript = Path(args.transcript) if args.transcript else telemetry.claude_code_transcript(Path.cwd())
    since, until = (datetime.fromtimestamp(parse_time(v)).astimezone() if v else None
                    for v in (args.since, args.until))
    tech = telemetry.collect(run, transcript, since, until)
    session = json.loads((run / "session.json").read_text(encoding="utf-8"))
    session["technical"] = tech
    findings.write_json(run / "session.json", session)
    history = run.parent / "telemetry.csv"
    telemetry.append_history(history, telemetry.history_row(run, session, tech))
    cost = (tech.get("cost_usd") or {}).get("total")
    tokens = tech.get("tokens") or {}
    print(f"agent: {tech['agent'].get('name')} {tech['agent'].get('version', '')}"
          + (f", transcript {transcript}" if transcript else ""))
    if tokens:
        print(f"tokens: {tokens.get('requests', 0)} requests, {tokens.get('output', 0):,} output, "
              f"{tokens.get('cache_read', 0):,} cache read; cost {'unknown' if cost is None else f'${cost:.2f}'}")
    print(f"session.json: technical updated; history row in {history}")
    if (run / "index.html").exists():
        report.build(run)
        print("report rebuilt")
    return EXIT_OK


def _finding_args(p: argparse.ArgumentParser, adding: bool) -> None:
    p.add_argument("dir", help="run folder")
    p.add_argument("id", help="B1.. bugs, A1.. accessibility, O1.. observations")
    p.add_argument("--title", required=adding)
    p.add_argument("--type", choices=list(report.TYPES), required=adding)
    p.add_argument("--status", choices=list(report.STATUSES), default="Confirmed" if adding else None)
    p.add_argument("--severity", choices=list(report.SEVERITIES))
    p.add_argument("--priority", choices=list(report.PRIORITIES))
    p.add_argument("--area")
    p.add_argument("--summary", help="one line for the finding list")
    p.add_argument("--preconditions", nargs="+", metavar="TEXT")
    p.add_argument("--steps", nargs="+", metavar="STEP", help="one argument per step, from the preconditions")
    p.add_argument("--expected")
    p.add_argument("--actual")
    p.add_argument("--automated", metavar="N/M", help="reproduced by automation, e.g. 3/3")
    p.add_argument("--manual", metavar="N/M", help="reproduced by a person, e.g. 1/1 or 'not tried'")
    p.add_argument("--evidence", nargs="+", metavar="PATH[::CAPTION]",
                   help="files relative to the run folder; added to the existing evidence")
    p.add_argument("--clear-evidence", action="store_true", help="drop the existing evidence first")
    p.add_argument("--notes")
    p.add_argument("--scope", choices=list(report.SCOPES))
    p.add_argument("--known-issue", dest="known_issue", metavar="K-N")


def subparsers(parser: argparse.ArgumentParser, common: argparse.ArgumentParser, **kwargs):
    group = parser.add_subparsers(**kwargs)
    add = group.add_parser

    def add_with_globals(name, **kw):
        return add(name, parents=[common], **kw)

    group.add_parser = add_with_globals
    return group


def add_parsers(sub, common: argparse.ArgumentParser) -> None:
    """The report and issues commands, on the subcommand group of either CLI."""
    p = sub.add_parser("screens", help="the session's screens: visited, controls never tried on each, and taps "
                                       "with no visible change (dead buttons?)")
    p.add_argument("dir", help="run folder")
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
    rp = rep.add_parser("diff", help="compare two runs (e.g. two builds): performance, findings, app log, screens")
    rp.add_argument("dir", help="run A (before)")
    rp.add_argument("other", help="run B (after)")
    rp = rep.add_parser("decision", help="log a decision autopilot took (logs/decisions.md and the report)")
    rp.add_argument("dir")
    rp.add_argument("key", help="decision key from autopilot.md, e.g. consent_banners")
    rp.add_argument("value", help="what was chosen, e.g. reject_non_essential")
    rp.add_argument("--why", help="what made it come up, e.g. 'cookie banner on first launch'")
    rp = rep.add_parser("telemetry", help="record technical data (agent tokens and cost, time per phase, activity) "
                                          "in session.json and <reports dir>/telemetry.csv, then rebuild")
    rp.add_argument("dir")
    rp.add_argument("--transcript", help="agent transcript (default: the newest Claude Code transcript of this "
                                         "project folder)")
    rp.add_argument("--since", help="count from this time (ISO, HH:MM:SS or epoch; default: transcript start)")
    rp.add_argument("--until", help="count up to this time (default: now)")
    settable = findings.SESSION_TEXT + findings.SESSION_INT + findings.SESSION_APP
    rp = rep.add_parser("set", help="set a session.json field: " + ", ".join(settable))
    rp.add_argument("dir")
    rp.add_argument("field", choices=list(settable))
    rp.add_argument("value")
    rp = rep.add_parser("result", help="record a test case or retested known issue result (session.json "
                                       "test_results); the same case and step again replaces it")
    rp.add_argument("dir")
    rp.add_argument("--case", required=True, help="test case name, e.g. 'TC-2 Add an item' or 'K-3 <title>'")
    rp.add_argument("--result", required=True, choices=list(report.TEST_RESULTS),
                    help="retest: pass = Fixed, fail = Still reproduces, blocked = Can't verify")
    rp.add_argument("--step", help="step number or name, when results are kept per step")
    rp.add_argument("--issue", help="retest: the known issue key, e.g. K-3")
    rp.add_argument("--finding", help="the finding written for a fail, e.g. B2")
    rp.add_argument("--note", help="why it was blocked, or e.g. '2 of 2 runs passed'")
    rp = rep.add_parser("add", help="add items to a session.json list: " + ", ".join(findings.SESSION_LISTS))
    rp.add_argument("dir")
    rp.add_argument("field", choices=list(findings.SESSION_LISTS))
    rp.add_argument("values", nargs="+")

    p = sub.add_parser("finding", help="write findings.json: add, update or retract a finding (validated at once)")
    fnd = subparsers(p, common, dest="finding_cmd", required=True)
    _finding_args(fnd.add_parser("add", help="a new finding"), adding=True)
    _finding_args(fnd.add_parser("update", help="change fields of a finding; evidence is added"), adding=False)
    rp = fnd.add_parser("retract", help="mark a finding Retracted, with the reason (never delete one)")
    rp.add_argument("dir")
    rp.add_argument("id")
    rp.add_argument("--reason", required=True)

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


def typed_log(serial: str, text: str, target: ui.Element | None, elements: list[ui.Element]) -> dict:
    """The `type` action's field and text for the action log (the text hidden when it could be a credential).
    The field is the one tapped with --index, else the focused field of the last observation."""
    field = target if target is not None and target.editable else inputs.focused_field(elements)
    return inputs.log_fields(text, field, inputs.secret_values(session.package(serial)))


# --- dashboard ---------------------------------------------------------------------------------

def dashboard_wanted(args) -> bool:
    """`session start` starts the dashboard when the project config says so (`dashboard: true`), unless
    --no-dashboard; --dashboard starts it whatever the config says."""
    if getattr(args, "dashboard", None) is not None:
        return args.dashboard
    config, _ = project.load()
    return bool(config.get("dashboard"))


def _dashboard_file(serial: str) -> Path:
    return state.device_dir(serial) / "dashboard.json"


def dashboard_start(serial: str, run: Path, worker: list[str], port: int = 8765) -> str:
    """Start the dashboard worker for `run` in the background (one per device) and return its URL.
    `worker` is the command that serves it, without --port."""
    running = state.read_json(_dashboard_file(serial)) or {}
    if running.get("pid") and is_alive(running["pid"]):
        if running.get("run") == str(run.resolve()):
            return dashboard.url(running["port"])
        terminate(running["pid"])  # a dashboard of an earlier run: this session gets its own
    port = dashboard.free_port(port)
    log = (state.device_dir(serial) / "dashboard.log").open("wb")
    proc = subprocess.Popen([*worker, "--port", str(port)], stdout=log, stderr=subprocess.STDOUT, **detached_kwargs())
    state.write_json(_dashboard_file(serial), {"pid": proc.pid, "port": port, "run": str(run.resolve())})
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            if sock.connect_ex((dashboard.HOST, port)) == 0:
                return dashboard.url(port)
        if proc.poll() is not None:
            raise RuntimeError(f"the dashboard did not start: see {state.device_dir(serial) / 'dashboard.log'}")
        time.sleep(0.2)
    return dashboard.url(port)


def dashboard_stop(serial: str) -> bool:
    running = state.read_json(_dashboard_file(serial)) or {}
    _dashboard_file(serial).unlink(missing_ok=True)
    if running.get("pid") and is_alive(running["pid"]):
        terminate(running["pid"])
        return True
    return False


def add_dashboard_parsers(sub) -> None:
    p = sub.add_parser("dashboard", help="a live page of the session on 127.0.0.1: the screen, actions, findings, "
                                         "screens, the time box, and Pause, Stop and notes for the agent")
    p.add_argument("--dir", help="run folder (default: the active or last session)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-live", dest="no_live", action="store_true", help="no live screen, observations only")
    p.add_argument("--stop", action="store_true", help="stop this device's dashboard")
    p = sub.add_parser("control", help="the dashboard's Pause, Stop and notes, from the command line; `wait` "
                                       "blocks while the session is paused")
    p.add_argument("what", choices=["status", "pause", "resume", "stop", "note", "wait"])
    p.add_argument("text", nargs="?", help="the note")
    p.add_argument("--timeout", type=float, default=600, help="`wait`: give up after this many seconds")
    p = sub.add_parser("_dashboard-worker", help=argparse.SUPPRESS)
    p.add_argument("dir")
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--no-live", dest="no_live", action="store_true")


def dashboard_run(serial: str, args) -> Path:
    run = Path(args.dir) if getattr(args, "dir", None) else session.latest_run_dir(serial)
    if run is None or not (run / "session.json").is_file():
        raise NotFound("no session for this device yet: start one with `session start`, or pass --dir RUN")
    return run


def serve_dashboard(serial: str, args, grab) -> int:
    """`_dashboard-worker`: serve until the session has been over for a while."""
    from .dashboard_page import PAGE

    board = dashboard.Dashboard(Path(args.dir), state.device_dir(serial), None if args.no_live else grab,
                                telemetry.claude_code_transcript(Path.cwd()))
    dashboard.serve(board, args.port, PAGE)
    return EXIT_OK


def cmd_control(serial: str, args, tool: str) -> int:
    run = session.run_dir(serial)
    if run is None:
        print("no active session")
        return EXIT_USAGE
    match args.what:
        case "pause" | "resume" | "stop":
            control.set_state(run, {"pause": "paused", "resume": "running", "stop": "stopped"}[args.what])
        case "note":
            control.add_note(run, args.text or "")
        case "wait":
            left = control.wait(run, args.timeout)
            for note in control.take_notes(run):
                print(f"NOTE from the person watching the dashboard: {note}")
            if left == "paused":
                print(f"still paused after {args.timeout:.0f} s: run `{tool} control wait` again, or wrap up")
                return EXIT_BLOCKED
            print("resumed: carry on" if left == "running" else "STOP requested: wrap up now")
            return EXIT_OK
    data = control.read(run)
    waiting = sum(1 for n in data["notes"] if not n.get("delivered"))
    print(f"session {data['state']}" + (f", {waiting} note(s) not read yet" if waiting else ""))
    return EXIT_OK


def add_plan_args(sp) -> None:
    """`session start` flags for what the session plan agreed, so starting a session is one call."""
    sp.add_argument("--time-box", dest="time_box", type=int, metavar="MIN", help="time box in minutes")
    sp.add_argument("--install-source", dest="install_source", help="where the build came from")
    for name, what in (("forbidden", "never done this session"), ("grants", "never-done items the plan allowed"),
                       ("approvals", "system changes approved on a personal phone, 'session plan: ...'")):
        sp.add_argument(f"--{name}", nargs="+", action="extend", metavar="ITEM", help=what)


def apply_plan(args, meta: dict) -> dict:
    """Put the plan flags of `session start` into the session metadata."""
    if args.time_box is not None:
        meta["time_box_min"] = args.time_box
    if args.install_source:
        meta.setdefault("app", {})["install_source"] = args.install_source
    for name in ("forbidden", "grants", "approvals"):
        if getattr(args, name):
            meta[name] = list(dict.fromkeys(getattr(args, name)))
    return meta


def print_contrast(last: dict | None, minimum: float, tool: str) -> int:
    """`contrast`: text contrast on the last observed screen (its screenshot and elements)."""
    if not last or not last.get("screenshot") or not Path(last["screenshot"]).is_file():
        print(f"no screenshot of the current screen: run `{tool} observe` first")
        return EXIT_USAGE
    elements = [ui.Element.from_dict(e) for e in last.get("elements", [])]
    results = contrast.check(Path(last["screenshot"]).read_bytes(), elements, last["screen"][0])
    print("\n".join(contrast.lines(results, minimum)))
    return EXIT_OK


def add_contrast_parser(sub) -> None:
    p = sub.add_parser("contrast", help="text contrast (WCAG ratio) of every text on the last observed screen")
    p.add_argument("--min", type=float, default=contrast.AA_NORMAL, help="list texts below this ratio (default 4.5)")


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


def add_device_list_args(p: argparse.ArgumentParser) -> None:
    """`devices --save ID --name NAME --test|--personal` and `devices --forget ID` on either CLI."""
    p.add_argument("--save", metavar="ID", help="save this serial/UDID in your device list (all projects)")
    p.add_argument("--name", help="a short name for --save, e.g. 'Pixel 7a'")
    kind = p.add_mutually_exclusive_group()
    kind.add_argument("--test", action="store_true", help="--save as a test device: system changes need no approval")
    kind.add_argument("--personal", action="store_true", help="--save as a personal device: every system change asks")
    p.add_argument("--forget", metavar="ID", help="remove a device from your device list")


def change_device_list(args, platform: str, kinds: dict[str, str]) -> int | None:
    """Handle --save / --forget; None when neither was given. `kinds`: connected id -> physical/emulator/simulator."""
    if args.forget:
        print(f"forgot {args.forget}" if devices.forget(args.forget) else f"{args.forget} wasn't in the device list")
        return EXIT_OK
    if not args.save:
        return None
    if not (args.name and (args.test or args.personal)):
        print("error: --save needs --name and --test or --personal")
        return EXIT_USAGE
    entry = devices.save(args.save, args.name, platform, kinds.get(args.save, "physical"), personal=args.personal)
    print(f"saved {entry['id']} as {entry['name']} ({'personal' if entry['personal'] else 'test'} device, "
          f"{entry['kind']}) in {devices.path()}")
    return EXIT_OK
