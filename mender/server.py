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

from mender.config import Config
from mender.demo import SCENARIOS, ScenarioError, apply_scenario, ensure_sandbox, reset
from mender.events import LOG
from mender.gitutil import head_sha, head_subject
from mender.loop import HealLoop

DASHBOARD = Path(__file__).resolve().parent.parent / "dashboard" / "index.html"


@dataclass
class AppState:
    """Guards against two heals running at once."""

    config: Config
    busy: bool = False
    last_head: str = ""
    watching: bool = True
    lock: threading.Lock = field(default_factory=threading.Lock)

    def claim(self) -> bool:
        with self.lock:
            if self.busy:
                return False
            self.busy = True
            return True

    def release(self) -> None:
        with self.lock:
            self.busy = False


def create_app(config: Config) -> FastAPI:
    ensure_sandbox(config.demo_template, config.target_repo)
    state = AppState(config=config)
    app = FastAPI(title="Mender", docs_url=None, redoc_url=None)

    def heal_now() -> None:
        """Run one heal cycle on a worker thread."""
        if not state.claim():
            return
        try:
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
                if state.watching and not state.busy:
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

    return app


app = None  # populated by `mender serve`
