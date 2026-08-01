# Demo video script — 3 minutes

Target: **2:50**, which leaves room to breathe. Roughly 400 words of narration.
Record at 1440×900 or larger so terminal text stays legible after compression.

## Before you hit record

```bash
# Terminal A — Ledger, clean and green
cd ~/Developer/Ledger && git checkout -q main && git reset -q --hard origin/main
.venv/bin/python -m pytest -q          # confirm 1398 passed

# Terminal B — Mender
cd ~/Developer/Mender
```

Close every other tab. Silence notifications. Have these open and ready:
- `github.com/Harhsitoo/ledger/pull/1`
- `github.com/Harhsitoo/mender/pull/1`
- Font size up two notches in both terminals.

---

## 0:00 — 0:22 · The problem

**Show:** Ledger's test suite passing — `1398 passed in 0.43s`.

> A test breaks at 2am. Someone reads the failure, finds the cause, writes a
> fix, runs the suite, opens a pull request. It's mechanical work, and it's the
> obvious thing to hand to an AI agent.
>
> Plenty of tools already do the obvious version. That's not the hard part.
> The hard part is this: the cheapest way to make a failing test pass is to
> delete the test.

---

## 0:22 — 0:40 · What Mender is

**Show:** the dashboard, idle, with the three gates visible.

> This is Mender. When a test breaks, Codex writes the fix — and Mender's job
> is to decide whether to believe it. Three gates, run independently, in a
> fresh process. The agent's own report is never taken as evidence.

---

## 0:40 — 1:35 · A real bug in a real codebase

**Show:** Terminal A. Make the change live, or paste a prepared commit.

> This is Ledger — a subscription billing engine, fourteen hundred tests.
> I'm going to refactor one function: replace `divmod` with integer division.
> Looks harmless.

**Run the suite. Let the failure count land on screen.**

> A hundred and fifty-eight tests fail. Every single one is a negative total —
> a credit. Truncation toward zero loses a minor unit, and money quietly
> disappears. This is exactly the kind of bug that ships.

**Switch to Terminal B. Run:**

```bash
.venv/bin/python -m mender heal --repo ~/Developer/Ledger
```

**Let it run — do not talk over the gates appearing.** Then:

> Twenty-six seconds. First attempt. And read the root cause — it didn't just
> make the test pass, it explains *why* truncation breaks negative remainders.

---

## 1:35 — 2:05 · The gate that matters

**Show:** the three PASS rows, then cut to `tests/test_loop.py`.

> Any model can produce a patch that turns a suite green. Mender assumes that's
> a claim and tries to disprove it.
>
> This test is the whole idea. When the agent deletes the failing test, the
> target gate passes. The regression gate passes — the suite really is clean.
> Only the integrity gate objects. Without it, the cheat ships behind a green
> tick.

---

## 2:05 — 2:30 · Codex wrote the code it repairs

**Show:** `git log --format='%an — %s'` in Ledger, then the authorship count.

> Ledger itself was written by Codex. It designed the architecture first —
> half-open billing periods, largest-remainder allocation, immutable price
> snapshots — then implemented every module with tests. Twenty-six hundred
> lines, authored by Codex in the commit history.
>
> So Codex builds the software, and Codex repairs it. Mender decides whether
> the repair is real.

---

## 2:30 — 2:50 · Close

**Show:** ledger PR #1, then mender PR #1.

> Every fix ends as a reviewable pull request with the root cause and the
> evidence attached. Mender proposes — a human still decides.
>
> And this one is Mender fixing a bug in Mender's own codebase.

**Hold on the mender PR for two seconds. End.**

---

## Notes

**If the live run makes you nervous**, the dashboard can replay a recorded
session — real events from a real heal, at their original speed. It is labelled
as a replay on screen, so it stays honest. Record the live version first; keep
the replay as the fallback.

**Do not narrate over the gates.** The three PASS rows landing in silence is
the most persuasive four seconds in the video.

**Trim ruthlessly.** If it runs over three minutes, cut the closing line about
Mender healing itself before you cut anything from the Ledger demo — the
158-test failure is the strongest evidence you have.
