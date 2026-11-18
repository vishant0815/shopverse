import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException

from .auth import signed_in_user_id
from .config import Settings, get_settings
from .messaging import Publisher, QueueFull
from .schemas import EventBatch

router = APIRouter(prefix="/api/v1/clickstream", tags=["clickstream"])


@lru_cache
def get_publisher() -> Publisher:
    settings = get_settings()
    return Publisher(settings.kafka_bootstrap_servers, settings.clickstream_topic)


@router.post("/events", status_code=202)
def record_events(
    batch: EventBatch,
    user_id: uuid.UUID | None = Depends(signed_in_user_id),
    publisher: Publisher = Depends(get_publisher),
    settings: Settings = Depends(get_settings),
) -> dict:
    now = datetime.now(timezone.utc)
    latest = now + timedelta(seconds=settings.max_clock_skew_seconds)
    for index, event in enumerate(batch.events):
        if event.occurred_at > latest:
            raise HTTPException(status_code=422, detail=f"events[{index}].occurred_at is ahead of the server clock")

    received_at = now.isoformat()
    owner = str(user_id) if user_id else None
    try:
        for event in batch.events:
            payload = event.model_dump(mode="json") | {"user_id": owner, "received_at": received_at}
            publisher.send(key=event.session_id, payload=payload)
    except QueueFull:
        raise HTTPException(
            status_code=503,
            detail="Events could not be queued. Send the same batch again; repeated event ids are counted once.",
        )
    return {"accepted": len(batch.events)}
