"""Command line entry point.

`mender serve` is the demo, but everything is reachable from the terminal so
the loop can be exercised without a browser — which matters when the browser is
the least reliable part of a live presentation.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import time
from pathlib import Path

from mender.config import Config
from mender.demo import SCENARIOS, ScenarioError, apply_scenario, ensure_sandbox, reset
from mender.gitutil import head_sha, head_subject, is_repo
from mender.loop import HealLoop
from mender.models import Incident, Phase

# -- terminal niceties ----------------------------------------------------

_TTY = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _TTY else text


def red(t: str) -> str:
    return _c("31", t)


def green(t: str) -> str:
    return _c("32", t)


def yellow(t: str) -> str:
    return _c("33", t)


def blue(t: str) -> str:
    return _c("36", t)


def dim(t: str) -> str:
    return _c("2", t)


def bold(t: str) -> str:
    return _c("1", t)


def rule(title: str = "") -> None:
    line = "─" * 66
    print(dim(line if not title else f"── {title} " + "─" * max(0, 62 - len(title))))


# -- commands -------------------------------------------------------------


def cmd_check(config: Config, _args: argparse.Namespace) -> int:
    report = HealLoop(config=config).check()
    if report.green:
        print(green(f"✓ green — {report.total} tests passed in {report.duration:.2f}s"))
        return 0

    print(red(f"✗ red — {len(report.failures)} of {report.total} tests failing"))
    for failure in report.failures:
        print(f"  {red('•')} {bold(failure.nodeid)}")
        print(f"    {dim(failure.headline)}")
    return 1


def cmd_heal(config: Config, args: argparse.Namespace) -> int:
    loop = HealLoop(config=config)

    print(bold(f"Watching {config.target_repo}"))
    print(dim(f"HEAD {head_sha(config.target_repo)} — {head_subject(config.target_repo)}"))
    rule()

    report = loop.check()
    if report.green:
        print(green(f"✓ suite is green ({report.total} tests). Nothing to heal."))
        return 0

    print(red(f"✗ {len(report.failures)} of {report.total} tests failing"))
    for failure in report.failures:
        print(f"  {red('•')} {failure.nodeid} — {dim(failure.headline)}")
    rule()

    started = time.monotonic()
    incident = loop.heal(report)
    _print_incident(incident)
    print(dim(f"\nTotal wall time: {time.monotonic() - started:.1f}s"))

    if args.keep_branch is False and incident.branch:
        pass  # branches are kept by default; nothing to do
    return 0 if incident.healed else 1


def _print_incident(incident: Incident) -> None:
    for attempt in incident.attempts:
        rule(f"attempt {attempt.n} · {attempt.fix.effort} effort")
        if attempt.fix.changed_files:
            print(f"  changed: {', '.join(attempt.fix.changed_files)}")
        else:
            print(dim("  no files changed"))
        print(dim(f"  codex took {attempt.fix.duration:.1f}s"))
        print()
        for gate in attempt.verdict.gates:
            mark = green("PASS") if gate.passed else red("FAIL")
            print(f"  [{mark}] {bold(gate.name)}")
            for line in gate.detail.strip().splitlines()[:6]:
                print(dim(f"        {line}"))
        print()

    rule()
    if incident.healed:
        print(green(bold("✓ HEALED")))
        print(f"\n{bold('Root cause')}\n{incident.root_cause}\n")
        if incident.branch:
            print(f"{bold('Branch')}  {blue(incident.branch)}")
        if incident.pr_url:
            print(f"{bold('PR')}      {blue(incident.pr_url)}")
        print(dim(f"\nHealed in {incident.elapsed:.1f}s over {len(incident.attempts)} attempt(s)."))
    else:
        print(red(bold("✗ GAVE UP")))
        print(dim(f"{len(incident.attempts)} attempts, {incident.elapsed:.1f}s."))
        print(dim("The last rejection is above. Nothing was merged."))


def cmd_watch(config: Config, _args: argparse.Namespace) -> int:
    loop = HealLoop(config=config)
    print(bold(f"Watching {config.target_repo} every {config.watch_interval}s. Ctrl-C to stop."))
    last_head = ""

    try:
        while True:
            head = head_sha(config.target_repo)
            if head != last_head:
                last_head = head
                print(dim(f"\n[{time.strftime('%H:%M:%S')}] HEAD {head} — {head_subject(config.target_repo)}"))
                report = loop.check()
                if report.green:
                    print(green(f"  ✓ green ({report.total} tests)"))
                else:
                    print(red(f"  ✗ {len(report.failures)} failing — healing"))
                    incident = loop.heal(report)
                    _print_incident(incident)
            time.sleep(config.watch_interval)
    except KeyboardInterrupt:
        print(dim("\nstopped"))
        return 0


def cmd_serve(config: Config, args: argparse.Namespace) -> int:
    import uvicorn

    from mender.server import create_app

    app = create_app(config)
    print(bold(f"Mender dashboard → http://{args.host}:{args.port}"))
    print(dim(f"watching {config.target_repo}"))
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def cmd_break(config: Config, args: argparse.Namespace) -> int:
    scenario = SCENARIOS.get(args.scenario)
    if scenario is None:
        print(red(f"unknown scenario {args.scenario!r}"))
        return cmd_scenarios(config, args)

    try:
        sha = apply_scenario(scenario, config.target_repo)
    except ScenarioError as exc:
        print(red(f"✗ {exc}"))
        return 1

    print(red(f"✗ broke {config.target_repo.name} @ {sha}"))
    print(f"  commit  {bold(scenario.title)}")
    print(f"  file    {scenario.file}")
    print(f"  breaks  {scenario.breaks}")
    print(dim(f"\n  {scenario.note}"))
    return 0


def cmd_reset(config: Config, _args: argparse.Namespace) -> int:
    if not _is_demo_sandbox(config):
        print(red("✗ refusing to reset a repository Mender did not create"))
        print(dim(f"  {config.target_repo} is not the bundled demo sandbox."))
        return 2

    reset(config.demo_template, config.target_repo)
    print(green(f"✓ {config.target_repo.name} rebuilt from {config.demo_template.name} — green again"))
    return 0


def cmd_scenarios(config: Config, _args: argparse.Namespace) -> int:
    print(bold("Seeded bugs\n"))
    for scenario in SCENARIOS.values():
        print(f"  {bold(scenario.key)}  {scenario.title}")
        print(dim(f"      {scenario.file} → {scenario.breaks}"))
        print(dim(f"      {scenario.note}"))
        print()
    return 0


# -- wiring ---------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    # `--repo` lives on a shared parent so it is accepted on either side of the
    # subcommand. `mender check --repo x` is what people actually type, and an
    # argparse default that only accepts `mender --repo x check` reads as a bug.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--repo",
        type=Path,
        # SUPPRESS, not None: the flag is defined on both the main parser and
        # every subparser so it works on either side of the subcommand. With a
        # None default the subparser would overwrite whatever the main parser
        # already parsed, silently ignoring `mender --repo x check`.
        default=argparse.SUPPRESS,
        help="repository to watch (default: the bundled demo sandbox)",
    )

    parser = argparse.ArgumentParser(
        prog="mender",
        parents=[common],
        description="A self-healing repo agent. Codex writes the fix; Mender proves it.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, help: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, help=help, parents=[common])

    add("check", "run the suite and report what is failing")

    heal = add("heal", "run the full detect → fix → verify → deliver loop once")
    heal.add_argument("--keep-branch", action="store_true", default=True, help=argparse.SUPPRESS)

    add("watch", "poll the repo and heal whenever HEAD moves and the suite is red")

    serve = add("serve", "run the live dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    broke = add("break", "seed a bug into the demo repo")
    broke.add_argument("--scenario", default="01", help="scenario key (see `mender scenarios`)")

    add("reset", "restore the demo sandbox to its pristine state")
    add("scenarios", "list the seeded bugs")

    return parser


_COMMANDS = {
    "check": cmd_check,
    "heal": cmd_heal,
    "watch": cmd_watch,
    "serve": cmd_serve,
    "break": cmd_break,
    "reset": cmd_reset,
    "scenarios": cmd_scenarios,
}


def _is_demo_sandbox(config: Config) -> bool:
    """True when the target is the sandbox Mender generates from the template."""
    return config.target_repo == Config.load().target_repo and config.demo_template.is_dir()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    config = Config.load()
    repo = getattr(args, "repo", None)
    if repo is not None:
        config = dataclasses.replace(config, target_repo=repo.expanduser().resolve())

    if args.command == "scenarios":
        return cmd_scenarios(config, args)

    # The bundled demo sandbox is generated on first use, so a fresh clone can
    # run the whole loop without a setup step.
    if _is_demo_sandbox(config) and not is_repo(config.target_repo):
        try:
            ensure_sandbox(config.demo_template, config.target_repo)
        except ScenarioError as exc:
            print(red(f"✗ {exc}"))
            return 2
        print(dim(f"created demo sandbox at {config.target_repo}"))

    if not is_repo(config.target_repo):
        print(red(f"✗ {config.target_repo} is not a git repository"))
        print(dim("  Mender needs git history to sandbox fixes and propose branches."))
        return 2

    return _COMMANDS[args.command](config, args)


if __name__ == "__main__":
    raise SystemExit(main())
