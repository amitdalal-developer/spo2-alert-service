"""HTTP API.

POST /readings                 one reading or a list of readings (REQ-1)
GET  /patients/{id}/alerts     active alerts for a patient (REQ-6)

Run with:  uvicorn spo2_monitor.api:app
"""
import asyncio
import contextlib
from typing import List, Optional, Union

from fastapi import Body, FastAPI, HTTPException

from .engine import AlertEngine
from .models import Alert, Reading


def create_app(
    engine: Optional[AlertEngine] = None,
    sweep_interval_s: float = 1.0,
    start_sweeper: bool = True,
) -> FastAPI:
    engine = engine or AlertEngine()

    async def sweep() -> None:
        while True:
            await asyncio.sleep(sweep_interval_s)
            engine.check_signal_loss()

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(sweep()) if start_sweeper else None
        yield
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="SpO2 Alert Service", lifespan=lifespan)
    app.state.engine = engine

    @app.post("/readings")
    def post_readings(
        body: Union[Reading, List[Reading]] = Body(...),
    ) -> dict:
        readings = body if isinstance(body, list) else [body]
        for reading in readings:
            engine.process(reading)
        return {"accepted": len(readings)}

    @app.get("/patients/{patient_id}/alerts", response_model=List[Alert])
    def get_alerts(patient_id: str) -> List[Alert]:
        alerts = engine.active_alerts(patient_id)
        if alerts is None:
            raise HTTPException(status_code=404, detail="Unknown patient")
        return alerts

    return app


app = create_app()
