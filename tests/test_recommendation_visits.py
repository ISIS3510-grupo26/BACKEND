"""BQ9: tasa de usuarios que visitan los restaurantes que la app les recomienda por compatibilidad, por mes."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

URL = "/api/v1/analytics/recommendation-visits"


@pytest.fixture
def client(tmp_path):
    object.__setattr__(settings, "db_path", str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


def rec_event(screen, user, spot="nitro-coffee", occurred_at=None, event_id=None):
    return {
        "eventId": event_id or str(uuid.uuid4()),
        "screen": screen,
        "spotId": spot,
        "userId": user,
        "durationMs": 0,
        "success": True,
        "deviceModel": "Pixel 7",
        "osName": "android",
        "osVersion": "14",
        "platform": "flutter",
        "occurredAt": occurred_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def opened(user, spot="nitro-coffee", **kw):
    return rec_event("recommendation_open", user, spot, **kw)


def visited(user, spot="nitro-coffee", **kw):
    return rec_event("recommendation_visit", user, spot, **kw)


def test_recommendation_events_require_spot_id(client):
    for screen in ("recommendation_open", "recommendation_visit"):
        e = rec_event(screen, "ana")
        e["spotId"] = None
        r = client.post("/api/v1/telemetry/page-loads", json={"events": [e]})
        assert r.status_code == 422 and screen in r.text

    r = client.post("/api/v1/telemetry/page-loads", json={"events": [opened("ana"), visited("ana")]})
    assert r.status_code == 202 and r.json() == {"accepted": 2, "duplicates": 0}


def test_recommendation_events_are_idempotent(client):
    # La app reenvia la visita con el mismo eventId si no le llego el 202: no cuenta dos veces.
    visit = visited("ana", event_id="visit-abc")
    client.post("/api/v1/telemetry/page-loads", json={"events": [opened("ana"), visit]})
    r = client.post("/api/v1/telemetry/page-loads", json={"events": [visit]})
    assert r.json() == {"accepted": 0, "duplicates": 1}
