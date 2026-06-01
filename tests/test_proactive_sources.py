from __future__ import annotations

import json

from drift_agent.proactive.sources import ProactiveSourceLoader


def test_static_source_loads_events(tmp_path) -> None:
    path = tmp_path / "proactive_sources.json"
    path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "type": "static",
                        "channel": "alert",
                        "name": "test",
                        "events": [
                            {
                                "event_id": "a1",
                                "title": "Build finished",
                                "content": "The build is ready.",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    events = ProactiveSourceLoader(path).load_events()

    assert len(events) == 1
    assert events[0].event_id == "a1"
    assert events[0].kind == "alert"
    assert events[0].source_name == "test"


def test_file_source_loads_events_and_bad_sources_do_not_block(tmp_path) -> None:
    events_path = tmp_path / "events.json"
    events_path.write_text(
        json.dumps([{"id": "c1", "title": "Interesting article"}]),
        encoding="utf-8",
    )
    sources_path = tmp_path / "sources.json"
    sources_path.write_text(
        json.dumps(
            {
                "sources": [
                    {"type": "file", "channel": "content", "path": str(events_path)},
                    {"type": "file", "channel": "content", "path": str(tmp_path / "missing.json")},
                    {"type": "static", "channel": "bad", "events": [{"title": "bad"}]},
                ]
            }
        ),
        encoding="utf-8",
    )

    events = ProactiveSourceLoader(sources_path).load_events()

    assert [event.event_id for event in events] == ["c1"]
    assert events[0].kind == "content"
