import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from .. import orders_client, service
from ..db import get_db
from ..providers import get_provider
from ..providers.fake_provider import FakeProvider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


@router.post("/stripe")
async def stripe_webhook(request: Request, stripe_signature: str = Header(default=""),
                         db: Session = Depends(get_db)):
    """Receives events from Stripe. No login: the signature is what proves it came from Stripe.

    Responses tell Stripe what to do next: 2xx = done, 5xx = retry later.
    """
    provider = get_provider()
    if isinstance(provider, FakeProvider):
        raise HTTPException(status_code=404, detail="Stripe isn't enabled.")

    payload = await request.body()  # the raw bytes are needed to check the signature
    try:
        event = provider.parse_webhook(payload, stripe_signature)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid signature.")

    try:
        # Database and HTTP work is blocking, so keep it off the event loop.
        outcome = await run_in_threadpool(service.handle_event, db, event)
    except orders_client.OrdersUnavailable:
        raise HTTPException(status_code=503, detail="Orders service unavailable; please retry.")

    logger.info("Stripe event %s (%s): %s", event.event_id, event.type, outcome)
    return {"received": True, "outcome": outcome}
