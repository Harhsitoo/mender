"""Recording and replaying a heal session.

The contract that matters: a replay reproduces exactly what was recorded, in
order, and cannot invent events the real run never produced.
"""

from __future__ import annotations

import json

from mender.events import EventLog
from mender.replay import Transcript, available, play, transcript_path


def _recorded(log: EventLog) -> Transcript:
    return Transcript.from_events("07", log.since(0))


def _session() -> EventLog:
    log = EventLog()
    log.emit("incident_detected", failed=1, total=41)
    log.emit("attempt_started", attempt=1, of=3)
    log.emit("gate", name="Integrity", passed=True, detail="clean")
    log.emit("healed", elapsed=18.0, attempts=1)
    return log


def test_records_every_event_in_order():
    transcript = _recorded(_session())

    assert [step["kind"] for step in transcript.steps] == [
        "incident_detected",
        "attempt_started",
        "gate",
        "healed",
    ]


def test_records_event_payloads():
    transcript = _recorded(_session())

    assert transcript.steps[0]["data"] == {"failed": 1, "total": 41}
    assert transcript.steps[2]["data"]["name"] == "Integrity"


def test_offsets_start_at_zero():
    transcript = _recorded(_session())

    assert transcript.steps[0]["offset"] == 0
    assert all(step["offset"] >= 0 for step in transcript.steps)


def test_sequence_numbers_are_not_carried_over():
    """The destination log assigns its own; a stale seq would corrupt the stream."""
    transcript = _recorded(_session())

    assert all("seq" not in step["data"] for step in transcript.steps)
    assert all("at" not in step["data"] for step in transcript.steps)


def test_records_whether_the_session_healed():
    assert _recorded(_session()).healed

    log = EventLog()
    log.emit("gave_up", attempts=3)
    assert not Transcript.from_events("07", log.since(0)).healed


def test_an_empty_session_cannot_be_recorded():
    import pytest

    with pytest.raises(ValueError):
        Transcript.from_events("07", [])


def test_round_trips_through_disk(tmp_path):
    original = _recorded(_session())
    path = original.save(tmp_path / "scenario-07.json")

    assert json.loads(path.read_text())["scenario"] == "07"
    assert Transcript.load(path).steps == original.steps


def test_replay_reproduces_the_session_exactly():
    original = _recorded(_session())
    destination = EventLog()
    play(original, destination, speed=1000)

    kinds = [event.kind for event in destination.since(0)]
    assert kinds == ["replay_started", *[s["kind"] for s in original.steps]]

    healed = destination.since(0)[-1]
    assert healed.data["elapsed"] == 18.0
    assert healed.data["attempts"] == 1


def test_replay_announces_itself():
    """A viewer must be able to tell a replay from a live run."""
    destination = EventLog()
    play(_recorded(_session()), destination, speed=1000)

    assert destination.since(0)[0].kind == "replay_started"


def test_replay_can_be_interrupted():
    destination = EventLog()
    play(_recorded(_session()), destination, speed=1000, should_stop=lambda: True)

    kinds = [event.kind for event in destination.since(0)]
    assert kinds == ["replay_started", "replay_stopped"]


def test_discovering_transcripts_on_disk(tmp_path):
    _recorded(_session()).save(tmp_path / "scenario-07.json")
    _recorded(_session()).save(tmp_path / "scenario-02.json")

    assert sorted(available(tmp_path)) == ["02", "07"]


def test_no_transcripts_is_not_an_error(tmp_path):
    assert available(tmp_path / "nothing-here") == {}


def test_transcript_path_naming(tmp_path):
    assert transcript_path("03", tmp_path).name == "scenario-03.json"
