# Mender

[![CI](https://github.com/Harhsitoo/mender/actions/workflows/ci.yml/badge.svg)](https://github.com/Harhsitoo/mender/actions/workflows/ci.yml)

**A self-healing repo agent.** When a test breaks, Mender diagnoses the failure, hands the problem to **Codex** to write the fix, then *independently verifies* that the fix is real — before opening a pull request with a plain-English root cause.

> Codex owns the fix. Mender owns the trust.

Built for the **ChatGPT Codex Hackathon 2026** — Agentic Coding track.

---

## The problem

A test goes red at 2am. A human has to wake up, read the failure, find the cause, write a fix, run the suite, and open a PR. That loop is mechanical, and it is the single most interruptible thing in a developer's life.

Plenty of tools will now pipe a stack trace into an LLM and commit whatever comes back. That is not the hard part. **The hard part is knowing whether the fix is real.**

An unsupervised coding agent has a well-known failure mode: the fastest way to make a failing test pass is to make the test stop asking. Delete the assertion. Add `@pytest.mark.skip`. Loosen the comparison. The suite goes green, the bug ships.

## What Mender does differently

Mender treats the fix as a **claim to be disproved**, not a result to be trusted. Every candidate patch runs a gauntlet of three independent gates in a fresh process:

| Gate | Question | Why it matters |
|------|----------|----------------|
| **A — Target** | Does the originally failing test now pass? | The obvious one. |
| **B — Regression** | Is the *entire* suite still green? | Catches fixes that break something else. |
| **C — Integrity** | Did the patch weaken the tests? | **The moat.** Rejects any patch that edits `tests/`, removes assertions, or adds `skip`/`xfail`. |

Gate C is what separates a demo from a tool. A patch that passes A and B by cheating on C is rejected, and the rejection is fed back to Codex as context for the next attempt. The agent gets caught by its own guardrail and has to do it properly.

## How it works

```
DETECT ──► COLLECT ──► FIX (Codex) ──► VERIFY ──► DELIVER
   ▲                        ▲              │           │
   │                        └─── retry ────┘           ▼
   └────────────── watch ──────────────────────  branch + PR
```

1. **Detect** — run the suite, parse pytest's JUnit XML into structured failures.
2. **Collect** — turn the traceback into a problem brief: implicated source files, the commit that likely caused it, the failing test's own source.
3. **Fix** — spin up an isolated `git worktree` and run `codex exec` inside it. Codex reads, edits, and iterates on real code.
4. **Verify** — in a *fresh process*, run Gates A, B, and C. Never trust the agent's self-report.
5. **Deliver** — on success, branch, commit, and open a PR with the root cause, the diff, and before/after evidence. On failure, feed the rejection back and retry (budget: 3).

Each attempt gets a **fresh worktree**, so a bad edit never compounds — but the prompt carries every prior rejection, which is what makes it an agent rather than a retry loop.

## Quick start

Codex CLI must be installed and authenticated:

```bash
npm install -g @openai/codex && codex login
```

Then:

```bash
uv venv --python 3.12 && uv pip install -e ".[dev]"
```

Run the dashboard and watch a repo heal itself:

```bash
.venv/bin/python -m mender serve
```

Open http://localhost:8000, click a seeded bug, and watch. Mender polls the
repo, so breaking it from another terminal works just as well:

```bash
.venv/bin/python -m mender break --scenario 02
```

Everything is reachable without a browser, which matters when the browser is
the least reliable part of a live demo:

| Command | What it does |
|---------|--------------|
| `mender check` | run the suite, report what is failing |
| `mender heal` | one full detect → fix → verify → deliver cycle |
| `mender watch` | poll and heal whenever HEAD moves to red |
| `mender serve` | the live dashboard |
| `mender break --scenario 03` | seed a bug |
| `mender record --scenario 03` | run a real heal and save it as a replayable transcript |
| `mender reset` | rebuild the sandbox, pristine and green |
| `mender scenarios` | list the seeded bugs |

Point it at your own repo with `--repo /path/to/project` (or `MENDER_TARGET_REPO`).

## Deploying

`Dockerfile` builds an image with git, Node, and the Codex CLI. Any host that
builds from a repo will do; `render.yaml` is included as a blueprint.

The one thing the container needs is `OPENAI_API_KEY`, set as a **secret in the
host's dashboard** — never in the repo. The entrypoint pipes it straight into
`codex login --with-api-key`, so the key is never written to disk by Mender and
never baked into an image layer. A ChatGPT subscription will not work here: that
token is device-bound, and API access is billed separately.

Two things change automatically in a container:

- **Codex's own sandbox is bypassed** (`MENDER_CODEX_BYPASS_SANDBOX=1`). The
  container is already the isolation boundary, and Codex's seccomp layer fails
  on hosts that restrict syscalls themselves.
- **Public mode** (`MENDER_PUBLIC=1`) adds a cooldown between heals and an
  hourly ceiling, because every click on a public URL spends real tokens.

### Replay mode

If Codex is not authenticated — no key, or credit exhausted — Mender does not
fail every click. It replays a recorded session instead: the real event log of
a real heal, played back at its original speed.

```bash
mender record --scenario 02   # writes replays/scenario-02.json
```

A transcript can only exist because the real loop produced it, and the UI says
plainly that it is replaying. Recording a session that did not heal is refused.
It also makes a good insurance policy for a live demo, where the thing most
likely to fail is the wifi.

## Measured behaviour

Against the bundled demo repo (41 tests), fixed by Codex on `gpt-5.5`:

| Seeded bug | Failing tests | Attempts | Time |
|------------|---------------|----------|------|
| Empty-cart `ZeroDivisionError` | 1 | 1 | 19.4s |
| Pagination off-by-one | 3 | 1 | 18.0s |
| `None` surname renders `"Prince None"` | 1 | 1 | 18.0s |
| Naive datetime leaks into aware comparison | 2 | 1 | 18.0s |

Those are not remembered numbers — each row is a recorded session in
`replays/`, and you can watch any of them back with `mender serve`.

Mender's own suite is 49 tests, and the ones that matter most are in
`tests/test_loop.py`: they script an engine that cheats — deleting the failing
test, adding a skip marker, fixing one test by breaking another — and assert
that the gates catch it, that the rejection reaches the next prompt, and that
only an honest patch is ever delivered.

One of those tests is the whole thesis in miniature:
`test_deleting_a_test_would_otherwise_look_green` confirms that deleting the
failing test produces a suite that runs perfectly clean. Target passes.
Regression passes. Only integrity objects.

## Layout

```
mender/
├── detect/     run the suite, parse failures out of JUnit XML
├── context/    traceback + imports → problem brief
├── sandbox/    isolated git worktree per attempt
├── fix/        the Codex hand-off (FixEngine protocol)
├── verify/     the three gates
├── deliver/    branch, commit, PR body
└── loop.py     the orchestrator state machine
demo-repo/      breakable Python project (template)
dashboard/      live red → green view, no build step
```

## Notes from building it

Three things were not obvious up front and are worth writing down.

**Codex must run hermetically.** A developer's `~/.codex/config.toml` can enable
plugins, MCP servers, and high reasoning effort. On the machine this was built
on, inheriting it turned a 31-second fix into a multi-minute one. Mender passes
`--ignore-user-config` and sets its own knobs, so a heal takes the same time on
every machine. Auth still comes from `CODEX_HOME`, so `codex login` is all a
user needs.

**Never inherit stdin.** `codex exec` appends piped stdin to its prompt. Run it
from a process whose stdin is a pipe that never closes — a web server, most CI
runners — and it blocks forever at 0% CPU with no error. Every subprocess
Mender spawns gets `stdin=DEVNULL`.

**Build artifacts are not a patch.** Running a suite writes `__pycache__`.
Bytecode under `tests/` looks exactly like an agent editing tests, and the
integrity gate rejected a perfectly good fix because of it. Artifacts are
filtered out of the diff before anything is judged.

## Status

Local watch mode is the shipped trigger. A GitHub Actions webhook trigger is
designed for — the detection stage is already decoupled — but not built.
Opening a real pull request needs `gh` and a remote and is off by default
(`MENDER_OPEN_PR=1`); without it, Mender stops at a local branch.
