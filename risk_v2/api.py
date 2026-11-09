"""Run the local candidate with: python -m risk_v2.api (default port 8001)."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import os
from threading import Lock
import time
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Path as PathParameter, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import legacy_api as v1
from .engine import ModelUnavailable, RiskEngine, load_artifact


class Assessment(BaseModel):
    reasons: list[str]
    temperature_rise_c_per_min: float | None
    observation_seconds: float
    policy_version: str
    model_version: str
    training_provenance: Literal["synthetic_demo", "real_sensor_data"]
    experimental: Literal[True]


class SensorStatus(BaseModel):
    device_id: str
    status: Literal["COLLECTING", "NORMAL", "ANOMALY", "FLAME_SIGNAL",
                    "THERMAL_WARNING", "THERMAL_DANGER", "RECOVERY_HOLD"]
    risk_level: Literal["UNKNOWN", "LOW", "MEDIUM", "HIGH"]
    source: Literal["SYSTEM", "AI", "DIRECT_SENSOR", "THERMAL_RULE", "SENSOR_FUSION", "HYSTERESIS"]
    sensors: v1.SensorValues
    ai: v1.AIResult
    alarm_suggested: bool
    timestamp: str
    online: bool
    assessment: Assessment


def create_app(artifact=None, policy=None):
    @asynccontextmanager
    async def lifespan(application):
        key = os.getenv("API_KEY", "")
        if len(key) < 32 or key != key.strip():
            raise RuntimeError("Set API_KEY to at least 32 characters with no surrounding whitespace")
        application.state.api_key = key.encode("utf-8")
        application.state.engine = RiskEngine(artifact or load_artifact(), policy)
        application.state.latest = {}
        application.state.lock = Lock()
        yield
        application.state.engine.devices.clear()
        application.state.latest.clear()

    application = FastAPI(title="Fire API - DS18B20 temperature and IR", version="2.0.0-demo", lifespan=lifespan)
    application.add_middleware(CORSMiddleware, allow_origins=v1.dashboard_origins(),
                               allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-API-Key"])

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return JSONResponse(status_code=422, content={"detail": [
            {"type": error["type"], "loc": list(error["loc"]), "msg": error["msg"]}
            for error in exc.errors()
        ]})

    @application.get("/health", response_model=v1.HealthStatus)
    def health(request: Request):
        body = {"ok": not request.app.state.engine.model_error,
                "model": "IsolationForest", "window_size": 10}
        return JSONResponse(status_code=200 if body["ok"] else 503, content=body)

    @application.post("/api/v1/sensor-data", dependencies=[Depends(v1.require_api_key)], response_model=SensorStatus)
    def sensor_data(payload: v1.SensorSample, request: Request):
        state = request.app.state
        with state.lock:
            now = time.monotonic()
            try:
                decision = state.engine.process(payload.device_id, payload.temperature, payload.infrared, now)
            except ModelUnavailable:
                raise HTTPException(status_code=503, detail="Model inference unavailable") from None
            result = {
                "device_id": payload.device_id, **decision,
                "sensors": {"temperature": payload.temperature, "infrared": payload.infrared},
                "timestamp": datetime.now(timezone.utc).isoformat(), "online": True,
            }
            state.latest[payload.device_id] = (now, result)
            return result

    @application.get("/api/v1/status/{device_id}", dependencies=[Depends(v1.require_api_key)], response_model=SensorStatus)
    def read_status(request: Request, device_id: Annotated[str, PathParameter(min_length=1, max_length=64, pattern=v1.DEVICE_PATTERN)]):
        state = request.app.state
        with state.lock:
            if device_id not in state.latest:
                raise HTTPException(status_code=404, detail="No samples received for this device")
            last, result = state.latest[device_id]
            return {**result, "online": time.monotonic() - last < 10}

    return application


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8001")), workers=1)
