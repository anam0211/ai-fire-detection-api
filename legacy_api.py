"""Advisory temperature/IR API. An AI anomaly does not confirm a fire."""

from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import secrets
from threading import Lock
import time
from typing import Annotated, Literal
from urllib.parse import urlsplit
import warnings

import joblib
import numpy as np
import sklearn
from fastapi import Depends, FastAPI, HTTPException, Path as PathParameter, Request, Security
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from sklearn.ensemble import IsolationForest
from sklearn.exceptions import InconsistentVersionWarning
from sklearn.utils.validation import check_is_fitted

ROOT = Path(__file__).resolve().parent
MODEL_FILE = ROOT / "model.joblib"
SKLEARN_VERSION = "1.6.1"
WINDOW = 10
ONLINE_TIMEOUT_SECONDS = 10
EXPECTED_FEATURES = ["temp_mean", "temp_max", "temp_change", "flame_ratio"]
DEVICE_PATTERN = r"^[A-Za-z0-9_-]+$"
logger = logging.getLogger("fire_api")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class SensorSample(BaseModel):
    device_id: str = Field(min_length=1, max_length=64, pattern=DEVICE_PATTERN)
    temperature: float = Field(
        strict=True, ge=-40, le=125, allow_inf_nan=False, description="Degrees Celsius"
    )
    infrared: int = Field(
        strict=True, ge=0, le=1,
        description="1=IR flame signal; normalize ESP32 active-LOW logic before POST",
    )


class SensorValues(BaseModel):
    temperature: float
    infrared: Literal[0, 1]


class AIResult(BaseModel):
    model: Literal["IsolationForest"]
    ready: bool
    result: Literal["INSUFFICIENT_DATA", "NORMAL", "ANOMALY", "MODEL_ERROR"]
    score: float | None = Field(allow_inf_nan=False, description="Decision score, not fire probability")


class SensorStatus(BaseModel):
    device_id: str
    status: Literal["COLLECTING", "NORMAL", "ANOMALY", "FLAME_SIGNAL"]
    risk_level: Literal["UNKNOWN", "LOW", "MEDIUM", "HIGH"]
    source: Literal["SYSTEM", "AI", "DIRECT_SENSOR"]
    sensors: SensorValues
    ai: AIResult
    alarm_suggested: bool
    timestamp: str = Field(description="UTC ISO-8601 time of the last accepted sample")
    online: bool


class HealthStatus(BaseModel):
    ok: bool
    model: Literal["IsolationForest"]
    window_size: Literal[10]


class ErrorResponse(BaseModel):
    detail: str


class HealthUnavailable(HealthStatus):
    detail: str


def features_from_window(samples):
    # Keep the trained feature order, dtype, calculation, and score threshold unchanged.
    a = np.asarray(samples, dtype=np.float32)
    temp, ir = a[:, 0], a[:, 1]
    return np.array([[
        float(temp.mean()), float(temp.max()), float(temp[-1] - temp[0]), float(ir.mean())
    ]], dtype=np.float32)


def model_score(model, samples):
    values = np.asarray(model.decision_function(features_from_window(samples)))
    if values.shape != (1,) or not np.isfinite(values).all():
        raise ValueError("Model must return one finite decision score")
    return float(values[0])


def load_model():
    """Load the existing trusted artifact; never train or write a model here."""
    try:
        if sklearn.__version__ != SKLEARN_VERSION:
            raise ValueError(f"scikit-learn must be {SKLEARN_VERSION}; got {sklearn.__version__}")
        if not MODEL_FILE.is_file():
            raise FileNotFoundError(f"Missing {MODEL_FILE}; restore the original model.joblib")
        with warnings.catch_warnings():
            warnings.simplefilter("error", InconsistentVersionWarning)
            artifact = joblib.load(MODEL_FILE)
        if artifact["sklearn_version"] != SKLEARN_VERSION:
            raise ValueError("Artifact scikit-learn version does not match the runtime")
        if artifact["window_size"] != WINDOW:
            raise ValueError("Artifact must use a window of 10 samples")
        if artifact["feature_names"] != EXPECTED_FEATURES:
            raise ValueError("Model feature order does not match API feature order")
        model = artifact["model"]
        if not isinstance(model, IsolationForest) or model.n_features_in_ != 4:
            raise ValueError("Expected a fitted IsolationForest with four features")
        check_is_fitted(model)
        model_score(model, [(30.0, 0)] * WINDOW)
        return model
    except Exception as exc:
        raise RuntimeError(f"Model initialization failed: {exc}") from exc


def dashboard_origins():
    value = os.getenv("DASHBOARD_ORIGINS", "http://localhost:5173,http://localhost:3000")
    origins = list(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))
    for origin in origins:
        parsed = urlsplit(origin)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username or parsed.password or parsed.path
                or parsed.query or parsed.fragment or "*" in origin):
            raise RuntimeError("DASHBOARD_ORIGINS must contain exact http(s) origins without paths")
    return origins


def require_api_key(
    request: Request, supplied: Annotated[str | None, Security(api_key_header)]
):
    if supplied is None or not secrets.compare_digest(
        supplied.encode("utf-8"), request.app.state.api_key
    ):
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key")


def create_app():
    @asynccontextmanager
    async def lifespan(application):
        key = os.getenv("API_KEY", "")
        if len(key) < 32 or key != key.strip():
            raise RuntimeError("Set API_KEY to at least 32 characters with no surrounding whitespace")
        application.state.api_key = key.encode("utf-8")
        application.state.model = load_model()
        application.state.model_error = False
        application.state.history = {}
        application.state.latest = {}
        application.state.lock = Lock()
        logger.info("Model ready: IsolationForest, scikit-learn %s, window=%s", sklearn.__version__, WINDOW)
        yield
        application.state.history.clear()
        application.state.latest.clear()

    application = FastAPI(title="AI IoT Flame Sensor API", version="1.1.0", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware, allow_origins=dashboard_origins(), allow_credentials=False,
        allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-API-Key"],
    )

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Do not reflect inputs/secrets or non-JSON floats (NaN/Infinity) in an error body.
        errors = [
            {"type": error["type"], "loc": list(error["loc"]), "msg": error["msg"]}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    @application.get("/health", response_model=HealthStatus,
                     responses={503: {"model": HealthUnavailable}})
    def health(request: Request):
        if request.app.state.model_error:
            return JSONResponse(status_code=503, content={
                "ok": False, "model": "IsolationForest", "window_size": WINDOW,
                "detail": "Model inference unavailable",
            })
        return {"ok": True, "model": "IsolationForest", "window_size": WINDOW}

    @application.post(
        "/api/v1/sensor-data", dependencies=[Depends(require_api_key)], response_model=SensorStatus,
        summary="Send one new sample; infer after 10 samples per device",
        responses={401: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    )
    def sensor_data(payload: SensorSample, request: Request):
        state = request.app.state
        with state.lock:
            # Stage the update so a failed POST can be retried without a hidden appended sample.
            last_sample = state.latest.get(payload.device_id)
            previous = state.history.get(payload.device_id, ())
            if last_sample is not None and time.monotonic() - last_sample[0] >= ONLINE_TIMEOUT_SECONDS:
                # A device returning from offline must not combine stale samples with a new session.
                previous = ()
            h = deque(previous, maxlen=WINDOW)
            h.append((payload.temperature, payload.infrared))
            score = None
            ai_result = "INSUFFICIENT_DATA"
            ready = len(h) == WINDOW
            if ready:
                try:
                    score = model_score(state.model, h)
                    ai_result = "ANOMALY" if score < 0 else "NORMAL"
                    state.model_error = False
                except Exception:
                    logger.exception("Model inference failed")
                    state.model_error = True
                    if payload.infrared != 1:
                        raise HTTPException(status_code=503, detail="Model inference unavailable") from None
                    # Preserve the direct IR signal even when AI is unavailable.
                    ai_result, ready = "MODEL_ERROR", False

            if payload.infrared == 1:
                status, risk, source = "FLAME_SIGNAL", "HIGH", "DIRECT_SENSOR"
            elif ai_result == "ANOMALY":
                status, risk, source = "ANOMALY", "MEDIUM", "AI"
            elif ai_result == "NORMAL":
                status, risk, source = "NORMAL", "LOW", "AI"
            else:
                status, risk, source = "COLLECTING", "UNKNOWN", "SYSTEM"

            result = {
                "device_id": payload.device_id,
                "status": status,
                "risk_level": risk,
                "source": source,
                "sensors": {"temperature": payload.temperature, "infrared": payload.infrared},
                "ai": {"model": "IsolationForest", "ready": ready, "result": ai_result, "score": score},
                "alarm_suggested": status in ("FLAME_SIGNAL", "ANOMALY"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "online": True,
            }
            state.history[payload.device_id] = h
            state.latest[payload.device_id] = (time.monotonic(), result)
            return result

    @application.get(
        "/api/v1/status/{device_id}", dependencies=[Depends(require_api_key)], response_model=SensorStatus,
        responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    def read_status(
        request: Request,
        device_id: Annotated[str, PathParameter(min_length=1, max_length=64, pattern=DEVICE_PATTERN)],
    ):
        state = request.app.state
        with state.lock:
            if device_id not in state.latest:
                raise HTTPException(status_code=404, detail="No samples received for this device")
            last_time, result = state.latest[device_id]
            return {**result, "online": (time.monotonic() - last_time) < ONLINE_TIMEOUT_SECONDS}

    return application


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")), workers=1)
