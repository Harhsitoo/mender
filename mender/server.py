"""FastAPI app: the live dashboard and its control surface.

The heal loop is synchronous and spends most of its life blocked on
subprocesses, so it runs on a worker thread and reports progress by appending
to the shared event log. The web layer only ever reads that log, which keeps
the two halves completely decoupled — the loop has no idea a browser exists.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from mender import __version__
from mender.config import Config
from mender.demo import SCENARIOS, ScenarioError, apply_scenario, ensure_sandbox, reset
from mender.events import LOG
from mender.fix.engine import codex_available
from mender.gitutil import head_sha, head_subject
from mender.loop import HealLoop
from mender.replay import Transcript, available as available_replays, play

DASHBOARD = Path(__file__).resolve().parent.parent / "dashboard" / "index.html"


@dataclass
class AppState:
    """Guards the heal loop: one at a time, and not too often.

    On a public URL every click spends real tokens, so `claim` doubles as a
    rate limiter. The caller gets a reason back rather than a bare False, so
    the dashboard can say *why* it refused.
    """

    config: Config
    busy: bool = False
    last_head: str = ""
    watching: bool = True
    live: bool = True
    finished_at: float = 0.0
    recent: list[float] = field(default_factory=list)
    last_scenario: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)

    def claim(self) -> str | None:
        """Take the heal slot, or return why it cannot be taken."""
        with self.lock:
            if self.busy:
                return "a heal is already running"

            if self.config.public_mode:
                now = time.time()

                waited = now - self.finished_at
                if self.finished_at and waited < self.config.heal_cooldown:
                    return f"cooling down — try again in {self.config.heal_cooldown - waited:.0f}s"

                self.recent = [t for t in self.recent if now - t < 3600]
                if len(self.recent) >= self.config.heals_per_hour:
                    return "hourly limit reached on this demo instance — try again later"
                self.recent.append(now)

            self.busy = True
            return None

    def release(self) -> None:
        with self.lock:
            self.busy = False
            self.finished_at = time.time()


def create_app(config: Config) -> FastAPI:
    ensure_sandbox(config.demo_template, config.target_repo)
    state = AppState(config=config)
    replays = available_replays()

    # Decided once, at startup: a missing or unfunded key should degrade to
    # replaying a real recorded session, not fail every click with auth errors.
    state.live = codex_available(config)
    if not state.live:
        print(
            "mender: Codex is unavailable — serving recorded sessions"
            if replays
            else "mender: Codex is unavailable and no recordings exist; heals will fail"
        )

    app = FastAPI(title="Mender", docs_url=None, redoc_url=None)

    def replay_now(scenario: str) -> bool:
        """Play back a recorded heal. Returns False if there is nothing to play."""
        path = replays.get(scenario) or (
            replays[sorted(replays)[0]] if replays else None
        )
        if path is None:
            return False
        play(Transcript.load(path), LOG, should_stop=lambda: not state.watching)
        return True

    def heal_now() -> None:
        """Run one heal cycle on a worker thread."""
        refusal = state.claim()
        if refusal:
            LOG.emit("throttled", reason=refusal)
            return
        try:
            if not state.live:
                if not replay_now(state.last_scenario):
                    LOG.emit(
                        "error",
                        message="Codex is not authenticated and no recorded session is available.",
                    )
                return

            loop = HealLoop(config=state.config)
            report = loop.check()
            if report.green:
                LOG.emit("suite_green", total=report.total)
                return
            loop.heal(report)
        except Exception as exc:  # a crashed loop must not kill the server
            LOG.emit("error", message=f"{type(exc).__name__}: {exc}")
        finally:
            state.release()

    def watcher() -> None:
        """Poll HEAD and heal whenever the repo moves to a red state.

        This is what makes the demo feel alive: break the repo in a terminal
        and the dashboard reacts on its own, with nobody touching the browser.
        """
        while True:
            try:
                # In replay mode nothing real ever breaks, so a HEAD change is
                # only ever a reset. Auto-firing a replay off that would look
                # like the agent reacting to something it did not see.
                if state.live and state.watching and not state.busy:
                    head = head_sha(state.config.target_repo)
                    if head and head != state.last_head:
                        state.last_head = head
                        LOG.emit(
                            "head_moved",
                            head=head,
                            subject=head_subject(state.config.target_repo),
                        )
                        heal_now()
            except Exception as exc:
                LOG.emit("error", message=f"watcher: {exc}")
            time.sleep(state.config.watch_interval)

    threading.Thread(target=watcher, daemon=True).start()

    # -- pages ------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        if not DASHBOARD.exists():
            return HTMLResponse("<h1>dashboard/index.html is missing</h1>", status_code=500)
        return HTMLResponse(DASHBOARD.read_text(encoding="utf-8"))

    @app.get("/events")
    async def events(since: int = 0) -> StreamingResponse:
        async def stream():
            last = since
            # A late-joining browser gets the backlog, then live updates.
            while True:
                for event in LOG.since(last):
                    last = event.seq
                    yield f"data: {json.dumps(event.as_dict())}\n\n"
                yield ": keep-alive\n\n"
                await asyncio.sleep(0.25)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # -- controls ---------------------------------------------------------

    @app.get("/api/status")
    async def status() -> JSONResponse:
        return JSONResponse(
            {
                "repo": str(state.config.target_repo),
                "head": head_sha(state.config.target_repo),
                "subject": head_subject(state.config.target_repo),
                "busy": state.busy,
                "watching": state.watching,
                "live": state.live,
                "replays": sorted(replays),
                "max_attempts": state.config.max_attempts,
                "seq": LOG.latest_seq(),
                "scenarios": [
                    {
                        "key": s.key,
                        "title": s.title,
                        "file": s.file,
                        "breaks": s.breaks,
                        "note": s.note,
                    }
                    for s in SCENARIOS.values()
                ],
            }
        )

    @app.post("/api/break/{key}")
    async def seed_bug(key: str) -> JSONResponse:
        scenario = SCENARIOS.get(key)
        if scenario is None:
            return JSONResponse({"error": f"unknown scenario {key}"}, status_code=404)
        if state.busy:
            return JSONResponse({"error": "a heal is already running"}, status_code=409)

        state.last_scenario = key

        if not state.live:
            # Nothing is actually broken in replay mode; the recording already
            # contains the commit that broke things.
            threading.Thread(target=heal_now, daemon=True).start()
            return JSONResponse({"ok": True, "replay": True})

        try:
            sha = await asyncio.to_thread(apply_scenario, scenario, state.config.target_repo)
        except ScenarioError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        LOG.emit("bug_seeded", scenario=key, title=scenario.title, file=scenario.file, sha=sha)
        return JSONResponse({"ok": True, "sha": sha})

    @app.post("/api/reset")
    async def reset_repo() -> JSONResponse:
        if state.busy:
            return JSONResponse({"error": "a heal is already running"}, status_code=409)
        await asyncio.to_thread(reset, state.config.demo_template, state.config.target_repo)
        LOG.clear()
        state.last_head = head_sha(state.config.target_repo)
        LOG.emit("reset", head=state.last_head)

        # Clearing the log also clears the "suite is green" the watcher emitted
        # at startup, which would leave the dashboard with nothing to report.
        # Re-establish it so a freshly reset repo still shows its test count.
        report = await asyncio.to_thread(HealLoop(config=state.config).check)
        LOG.emit("suite_green" if report.green else "suite_red", total=report.total)
        return JSONResponse({"ok": True, "total": report.total, "green": report.green})

    @app.post("/api/heal")
    async def manual_heal() -> JSONResponse:
        if state.busy:
            return JSONResponse({"error": "a heal is already running"}, status_code=409)
        threading.Thread(target=heal_now, daemon=True).start()
        return JSONResponse({"ok": True})

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        """Liveness probe for the host. Deliberately does no work."""
        return JSONResponse({"ok": True, "version": __version__})

    return app


app = None  # populated by `mender serve`
