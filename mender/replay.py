"""Recording and replaying real heal sessions.

A hosted demo has two failure modes that have nothing to do with whether the
agent works: the API key runs out of credit, and the venue wifi dies during a
presentation. Both leave a reviewer looking at a page that appears broken.

So Mender can record a genuine heal — every event, with its real timing — and
play it back later. This is never a simulation of behaviour the agent does not
have: a transcript can only exist because the real loop produced it. The UI
always says when it is replaying, because a replay presented as live would be
a lie about what just happened.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from mender.events import Event, EventLog

REPLAY_DIR = Path(__file__).resolve().parent.parent / "replays"

# Fields the log assigns itself; a replay must not carry the originals.
_REASSIGNED = {"seq", "at"}


@dataclass(frozen=True)
class Transcript:
    """A recorded heal: what happened, and how long each step took."""

    scenario: str
    recorded_at: str
    duration: float
    steps: tuple[dict[str, Any], ...]

    @classmethod
    def from_events(cls, scenario: str, events: list[Event]) -> Transcript:
        if not events:
            raise ValueError("cannot record an empty session")

        start = events[0].at
        steps = tuple(
            {
                "offset": round(event.at - start, 3),
                "kind": event.kind,
                "data": {k: v for k, v in event.data.items() if k not in _REASSIGNED},
            }
            for event in events
        )
        return cls(
            scenario=scenario,
            recorded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            duration=round(events[-1].at - start, 3),
            steps=steps,
        )

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "scenario": self.scenario,
                    "recorded_at": self.recorded_at,
                    "duration": self.duration,
                    "steps": list(self.steps),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, path: Path) -> Transcript:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            scenario=raw["scenario"],
            recorded_at=raw.get("recorded_at", ""),
            duration=float(raw.get("duration", 0)),
            steps=tuple(raw.get("steps", ())),
        )

    @property
    def healed(self) -> bool:
        return any(step["kind"] == "healed" for step in self.steps)


def transcript_path(scenario: str, directory: Path | None = None) -> Path:
    return (directory or REPLAY_DIR) / f"scenario-{scenario}.json"


def available(directory: Path | None = None) -> dict[str, Path]:
    """Recorded scenarios, keyed by scenario id."""
    root = directory or REPLAY_DIR
    if not root.is_dir():
        return {}
    found = {}
    for path in sorted(root.glob("scenario-*.json")):
        found[path.stem.removeprefix("scenario-")] = path
    return found


def play(
    transcript: Transcript,
    log: EventLog,
    speed: float = 1.0,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    """Re-emit a recorded session into `log`, preserving its original pacing.

    The waits are real. A heal that took twenty seconds replays over twenty
    seconds, because compressing it would misrepresent how long the agent
    actually takes — which is one of the few things a viewer can measure.
    """
    log.emit("replay_started", scenario=transcript.scenario, recorded_at=transcript.recorded_at)

    elapsed = 0.0
    for step in transcript.steps:
        if should_stop and should_stop():
            log.emit("replay_stopped", scenario=transcript.scenario)
            return

        wait = max(0.0, float(step["offset"]) - elapsed) / max(speed, 0.01)
        if wait:
            time.sleep(wait)
        elapsed = float(step["offset"])

        log.emit(step["kind"], **step.get("data", {}))
