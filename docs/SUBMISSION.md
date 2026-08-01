# Mender — Project Description

**ChatGPT Codex Hackathon 2026**

| | |
|---|---|
| **Project** | Mender — a self-healing repo agent |
| **Track** | Agentic Coding |
| **Team** | Harshit ([@Harhsitoo](https://github.com/Harhsitoo)) |
| **Agent repository** | https://github.com/Harhsitoo/mender |
| **Application repository** | https://github.com/Harhsitoo/ledger |
| **A pull request Mender opened** | https://github.com/Harhsitoo/ledger/pull/1 |
| **Deployed application** | _(add the live URL here)_ |
| **Demo video** | _(add the video link here)_ |

---

## 1. The problem

A test goes red at 2am. Someone has to wake up, read the failure, find the
cause, write a fix, run the suite, and open a pull request. That loop is
mechanical, it is the most interruptible thing in a developer's life, and it is
the obvious thing to hand to an agent.

A wave of tools now does the obvious version: pipe the stack trace to a model,
commit whatever comes back. **That is not the hard part.** Getting a language
model to produce a patch that turns a red suite green is easy, and by itself it
is worth very little — because the cheapest way to make a failing test pass is
to stop the test from asking.

An unsupervised coding agent has a well-documented failure mode. Delete the
assertion. Add `@pytest.mark.skip`. Loosen the comparison. Edit the fixture.
Every one of those produces a green suite, a confident summary, and a shipped
bug. The suite going green is a **claim**, not evidence — and nothing in the
usual pipeline is designed to disprove it.

That is the gap Mender addresses. Not *can an agent write a fix*, but **can you
trust the one it wrote.**

---

## 2. What Mender does

Mender watches a repository. When a test breaks it diagnoses the failure, hands
the problem to Codex to write a real fix in an isolated checkout, then
independently verifies that fix before any human sees it — and opens a pull
request with a plain-English root cause and the evidence attached.

```
DETECT ──► COLLECT ──► FIX (Codex) ──► VERIFY ──► DELIVER
   ▲                        ▲             │           │
   │                        └─── retry ───┘           ▼
   └────────────── watch ─────────────────────  branch + PR
```

1. **Detect** — run the suite, parse pytest's JUnit XML into structured failures.
2. **Collect** — build a problem brief: the traceback, the implicated source, the
   commit that likely caused it, and the failing test's own source.
3. **Fix** — create a disposable `git worktree` and run `codex exec` inside it.
   Codex reads, edits, runs the suite, and iterates on real files.
4. **Verify** — in a *fresh process*, run three gates. Codex's own report is
   recorded but never treated as evidence.
5. **Deliver** — branch, commit, and open a PR with the root cause and gate
   results. On failure, feed the rejection back and retry.

### The three gates

| Gate | Question | Why it exists |
|------|----------|---------------|
| **Integrity** | Did the patch play fair? | Rejects any patch that edits test code, deletes assertions, adds `skip`/`xfail`, or deselects tests via config. |
| **Target** | Does the broken test pass now? | The obvious one. |
| **Regression** | Is the whole suite still green? | Catches a fix that repairs one test by breaking two others. |

All three must pass. A failure becomes the feedback for the next attempt, and
the reasoning budget escalates — low, then medium, then high — so attempt two is
not the same question asked the same way.

**Integrity is the contribution.** Mender's own test suite contains
`test_deleting_a_test_would_otherwise_look_green`, which proves the point: when
the agent deletes the failing test, the Target gate passes and the Regression
gate passes, because the resulting suite genuinely is clean. Only Integrity
objects. Without it, the cheat ships behind a green tick.

Each attempt gets a **fresh worktree** cut from the same broken commit, so a bad
edit never compounds. What carries forward is the rejection, which is the
difference between an agent and a retry loop.

---

## 3. How Codex is used

Codex appears in this project twice, and both are agentic rather than
autocomplete.

### As the engine of the product

Mender is not a tool that Codex helped write. **Codex is the runtime.** Every
fix Mender proposes is written by `codex exec` running non-interactively inside
a sandboxed worktree, where it reads the code, edits files, runs pytest, and
iterates until it believes it is done. Mender supplies the brief, the isolation,
and the judgement. Codex does the engineering.

Two implementation details that took real work:

- **Hermetic execution.** A developer's `~/.codex/config.toml` can enable
  plugins, MCP servers, and high reasoning effort. On the machine this was built
  on, inheriting it turned a 31-second fix into a multi-minute one. Mender passes
  `--ignore-user-config` and sets its own parameters, so a heal takes the same
  time on every machine.
- **Detached stdin.** `codex exec` appends piped stdin to its prompt. Run from a
  process whose stdin is a pipe that never closes — a web server, most CI
  runners — and it blocks indefinitely at 0% CPU with no error. Every subprocess
  gets `stdin=DEVNULL`.

### As the builder of the application it repairs

To demonstrate Mender on real code rather than a toy, we built **Ledger**, a
subscription billing engine — and Codex wrote it.

Codex was given the domain and asked to design it first. It produced a 298-line
design document that independently identified the correctness traps that
actually bite in billing: half-open `[start, end)` periods so no instant falls
in two cycles, largest-remainder allocation with deterministic ordering so
pennies are neither lost nor awarded at random, `Fraction`-based intermediate
arithmetic, immutable price snapshots so a later price change cannot rewrite
history, and a hard rule that the library never calls `datetime.now()` itself.

It then implemented all nine modules with tests, one commit per task, each
commit recording the prompt it was given and what it reported back.

**Authorship, from `git log`:**

| Author | Lines added |
|---|---|
| **Codex** | **2,598** |
| Scaffolding (harness, README, test config) | 103 |

That is planning, multi-step execution, and self-review across a whole codebase
— verifiable in the commit history, not asserted here.

---

## 4. Evidence

### Mender heals a real 1,398-test codebase

A refactor of Ledger's `allocate_equal` replaced `divmod` with `int(x / n)`.
Every positive case still passed. **158 tests failed — every one a negative
total**, because truncation toward zero produces a negative remainder that the
"first recipients get the extra unit" rule never distributes. Credits silently
lost a minor unit. This is exactly the class of bug that ships.

Mender healed it in **26.1 seconds, on the first attempt**, with all three gates
green. Its diagnosis:

> `int(total / count)` truncates negative values toward zero, producing a
> negative remainder that never distributes units. `divmod` uses floor division,
> yielding a non-negative remainder and conserving negative totals correctly in
> caller order.

Codex's patch kept the readable form the refactor was reaching for and restored
`divmod` for floor semantics — it fixed the bug **without undoing the intent of
the change**. The pull request is public: [ledger#1](https://github.com/Harhsitoo/ledger/pull/1).

### Reproducible sessions

Four seeded bugs in the bundled demo repository, each a different shape — a
crash, a silent wrong value, a silent wrong value whose source never appears in
the traceback, and a type error across a module boundary. All heal on the first
attempt:

| Bug | Failing tests | Attempts | Time |
|---|---|---|---|
| Empty-cart `ZeroDivisionError` | 1 | 1 | 19.4s |
| Pagination off-by-one | 3 | 1 | 18.0s |
| `None` surname renders `"Prince None"` | 1 | 1 | 18.0s |
| Naive datetime in an aware comparison | 2 | 1 | 18.0s |

Each row is a recorded session committed to `replays/`, not a remembered number.
Any of them can be replayed from the dashboard.

---

## 5. Technical stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | The repositories under test are Python; one toolchain end to end. |
| Fix engine | **OpenAI Codex CLI** (`codex exec`) | Agentic: reads, edits, runs tests, iterates. Behind a `FixEngine` protocol so the loop never depends on one vendor. |
| Isolation | `git worktree` + subprocess | A real checkout on a real filesystem, shared object store, disposable. No Docker dependency at runtime. |
| Detection | pytest JUnit XML | Structured failures with file and line, rather than scraping console output. |
| Web | FastAPI + server-sent events | The heal loop is synchronous and blocks on subprocesses; it runs on a worker thread and reports by appending to an event log the web layer only reads. |
| Dashboard | Single HTML file, no build step | Nothing to compile, nothing to break at demo time. |
| Deployment | Docker (`python:3.12-slim` + git + Node + Codex CLI) | Runs on any host that builds from a repository. |

**Scale:** Mender is 3,097 lines of application code, 1,046 lines of tests
(77 tests), and a 704-line dashboard, across 6 commits. Ledger is 1,589 lines of
application code and 671 lines of tests (**1,398 tests**), across 9 commits.

### Deployment safety

A public URL means strangers can spend tokens, so the hosted instance enforces a
cooldown between heals and an hourly ceiling, and surfaces the reason when it
refuses rather than failing silently. If Codex is unauthenticated or credit runs
out, Mender does not break — it **replays a recorded session**: the real event
log of a real heal, played back at its original speed, clearly labelled in the
UI as a replay. A transcript can only exist because the real loop produced it,
and recording a session that did not heal is refused.

---

## 6. Why this matters

Every organisation adopting autonomous coding agents runs into the same
question, usually after the first bad merge: *how do we know the agent actually
fixed it?* The industry answer today is "a human reviews the PR," which
reintroduces the bottleneck the agent was supposed to remove.

Mender's answer is that the verification should be **mechanical, adversarial,
and independent of the agent that wrote the patch**. The integrity gate is a
small idea — check that the patch did not change the question — but it is the
difference between an agent you can leave running and one you have to watch.

The loop always ends at a reviewable branch. Mender proposes; a human disposes.
It never merges, and it never touches a default branch.

---

## 7. Running it

```bash
npm install -g @openai/codex && codex login
git clone https://github.com/Harhsitoo/mender && cd mender
uv venv --python 3.12 && uv pip install -e ".[dev]"
.venv/bin/python -m mender serve
```

Open http://localhost:8000 and pick a bug. Or point it at your own repository:

```bash
.venv/bin/python -m mender heal --repo /path/to/your/project
```

---

## 8. Tooling disclosure

The guidelines permit and encourage the use of AI tools, so for completeness:

- **Ledger** — the application, its tests, and its design document were written
  by **OpenAI Codex** (2,598 of 2,701 lines). Authorship is recorded in git.
- **Mender** — the agent's own scaffolding was written with Claude Code. Its
  purpose, architecture, and every fix it produces are Codex.
- All measurements in this document come from the committed repositories and can
  be reproduced by cloning them.
