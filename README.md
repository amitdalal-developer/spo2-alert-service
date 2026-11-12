# SpO2 Alert Service

Takes in per-patient SpO2 readings and manages `LOW_SPO2` and `SIGNAL_LOSS` alerts (see `Requirements.rtf`).

## Run
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn spo2_monitor.api:app          # http://localhost:8000/docs
.venv/bin/python -m pytest -q                   # run tests
```

## API
| Method | Path | Body / Response |
|---|---|---|
| POST | `/readings` | One reading or a JSON list: `{"patient_id": "P-001", "ts": 1730480400000, "spo2": 88, "quality": "good"}` → `{"accepted": n}`. Invalid input → 422. |
| GET | `/patients/{id}/alerts` | `[{"type": "LOW_SPO2", "start_time": <epoch ms>}, ...]`. Unknown patient → 404. |

## Alert rules
Readings arrive at 1 Hz, so a "10 s" window is the **last 10 good readings**.

| Req | Rule | Tests |
|---|---|---|
| REQ-1 | Multiple patients, with independent state; single or batch POST | `test_req1_*` |
| REQ-2 | Raise `LOW_SPO2` when 10 consecutive good readings are `< 90`. `start_time` = `ts` of the first reading in that run. | `test_req2_*` |
| REQ-3 | Clear `LOW_SPO2` when 10 consecutive good readings are `>= 92` | `test_req3_*` |
| REQ-4 | `quality: "poor"` readings are skipped: they never count toward, reset or break a window, and never raise or clear an alert | `test_req4_*` |
| REQ-5 | Raise `SIGNAL_LOSS` when no reading of **any** quality has arrived for > 30 s (server arrival time, checked every 1 s). Clear it only on the next **good** reading. | `test_req5_*` |
| REQ-6 | `GET /patients/{id}/alerts` returns active alerts with type and start time | `test_req6_*` |

Design decisions not stated in the requirements:
- A good reading of 90–91 breaks both the low run and the clear run.
- An alert is raised only once while it is active.
- `SIGNAL_LOSS.start_time` is the server time when the loss was detected.
- When `SIGNAL_LOSS` is raised, any window in progress is reset; an active `LOW_SPO2` stays active.
- Readings are processed in arrival order.
- `quality` must be `good` or `poor`, and `spo2` must be 0–100.
- State is held in memory, so it is lost when the server restarts.

## Layout
- `spo2_monitor/engine.py`: alert state machine (pure logic, injectable clock)
- `spo2_monitor/api.py`: FastAPI app plus a background sweep that checks for signal loss
- `spo2_monitor/models.py`, `spo2_monitor/clock.py`
- `tests/test_engine.py`, `tests/test_api.py`
