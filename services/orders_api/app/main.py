import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bson import ObjectId
from fastapi import FastAPI, HTTPException, Query, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pymongo.errors import PyMongoError

from .config import get_settings
from .db import orders_collection
from .metrics import ERRORS, REQUEST_DURATION, REQUESTS

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("orders-api")
event_log_file = os.getenv("ORDERS_API_LOG_FILE")
if event_log_file:
    event_log_path = Path(event_log_file)
    event_log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.addHandler(logging.FileHandler(event_log_path, encoding="utf-8"))

app = FastAPI(title="Orders API", version="0.1.0")
settings = get_settings()
logger.info(
    json.dumps(
        {
            "event": "deployment",
            "service": "orders-api",
            "version": app.version,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )
)


@app.middleware("http")
async def observe_requests(request: Request, call_next):  # type: ignore[no-untyped-def]
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    except Exception as exc:
        ERRORS.labels(request.url.path, type(exc).__name__).inc()
        raise
    finally:
        elapsed = time.perf_counter() - started
        REQUESTS.labels(request.method, request.url.path, str(status_code)).inc()
        REQUEST_DURATION.labels(request.method, request.url.path).observe(elapsed)
        logger.info(
            json.dumps(
                {
                    "service": "orders-api",
                    "method": request.method,
                    "path": request.url.path,
                    "status": status_code,
                    "durationMs": round(elapsed * 1000, 2),
                }
            )
        )


@app.get("/health")
def health() -> dict[str, str]:
    try:
        orders_collection(settings.mongodb_uri).database.client.admin.command("ping")
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail="MongoDB unavailable") from exc
    return {"status": "ok", "service": "orders-api"}


@app.get("/orders/search")
def search_orders(
    customer_id: str = Query(alias="customerId"),
    status: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    query: dict[str, Any] = {"customerId": customer_id}
    if status:
        query["status"] = status
    try:
        documents = list(
            orders_collection(settings.mongodb_uri).find(query).sort("createdAt", -1).limit(limit)
        )
    except PyMongoError as exc:
        ERRORS.labels("/orders/search", type(exc).__name__).inc()
        raise HTTPException(status_code=503, detail="Order search unavailable") from exc
    for document in documents:
        if isinstance(document.get("_id"), ObjectId):
            document["_id"] = str(document["_id"])
    return {"orders": documents, "count": len(documents)}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
