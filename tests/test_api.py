import pytest
from fastapi.testclient import TestClient

from spo2_monitor.api import create_app
from spo2_monitor.clock import FakeClock
from spo2_monitor.engine import AlertEngine

T0 = 1730480400000


@pytest.fixture
def clock():
    return FakeClock(start_ms=T0)


@pytest.fixture
def engine(clock):
    return AlertEngine(clock=clock)


@pytest.fixture
def client(engine):
    with TestClient(create_app(engine=engine, start_sweeper=False)) as c:
        yield c


def reading(spo2, i=0, pid="P-001", quality="good"):
    return {"patient_id": pid, "ts": T0 + i * 1000, "spo2": spo2, "quality": quality}


def test_req1_accepts_single_reading(client):
    r = client.post("/readings", json=reading(97))
    assert r.status_code == 200
    assert r.json() == {"accepted": 1}


def test_req1_accepts_batch_for_multiple_patients(client):
    batch = [reading(85, i, "P-001") for i in range(10)]
    batch += [reading(97, i, "P-002") for i in range(10)]
    r = client.post("/readings", json=batch)
    assert r.json() == {"accepted": 20}
    assert client.get("/patients/P-001/alerts").json() == [
        {"type": "LOW_SPO2", "start_time": T0}
    ]
    assert client.get("/patients/P-002/alerts").json() == []


@pytest.mark.parametrize(
    "bad",
    [
        {"patient_id": "P-001", "ts": T0, "spo2": 101, "quality": "good"},
        {"patient_id": "P-001", "ts": T0, "spo2": 95, "quality": "meh"},
        {"patient_id": "", "ts": T0, "spo2": 95, "quality": "good"},
        {"patient_id": "P-001", "spo2": 95, "quality": "good"},
    ],
)
def test_req1_rejects_invalid_reading(client, bad):
    assert client.post("/readings", json=bad).status_code == 422


def test_req6_unknown_patient_404(client):
    assert client.get("/patients/nobody/alerts").status_code == 404


def test_req6_returns_type_and_start_time(client, engine, clock):
    client.post("/readings", json=[reading(85, i) for i in range(10)])
    clock.advance(31_000)
    engine.check_signal_loss()
    body = client.get("/patients/P-001/alerts").json()
    assert body == [
        {"type": "LOW_SPO2", "start_time": T0},
        {"type": "SIGNAL_LOSS", "start_time": T0 + 31_000},
    ]


def test_req5_background_sweeper_raises_signal_loss(clock):
    import time

    engine = AlertEngine(clock=clock)
    app = create_app(engine=engine, sweep_interval_s=0.01)
    with TestClient(app) as c:
        c.post("/readings", json=reading(97))
        clock.advance(31_000)
        deadline = time.time() + 2
        while time.time() < deadline:
            if c.get("/patients/P-001/alerts").json():
                break
            time.sleep(0.02)
        assert c.get("/patients/P-001/alerts").json()[0]["type"] == "SIGNAL_LOSS"
