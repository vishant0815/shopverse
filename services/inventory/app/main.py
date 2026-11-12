"""Inventory API: stock levels for shoppers (availability) and for sellers (stock to manage).

Stock is changed by orders only through Kafka commands (see stock.py); this API lets a
seller set what's on the shelf, and lets the storefront show what's left.
"""

import uuid

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import CurrentUser, seller_or_admin
from .db import get_db
from .models import StockItem

app = FastAPI(title="Shopverse inventory service", docs_url="/api/v1/inventory/docs",
              openapi_url="/api/v1/inventory/openapi.json")

MAX_IDS = 100


def parse_ids(raw: str) -> list[uuid.UUID]:
    try:
        ids = list(dict.fromkeys(uuid.UUID(part.strip()) for part in raw.split(",") if part.strip()))
    except ValueError:
        raise HTTPException(status_code=400, detail="variant_ids must be a comma-separated list of ids.")
    if len(ids) > MAX_IDS:
        raise HTTPException(status_code=400, detail=f"Ask for at most {MAX_IDS} variants at a time.")
    return ids


class Availability(BaseModel):
    variant_id: uuid.UUID
    available: int


class StockLevel(BaseModel):
    variant_id: uuid.UUID
    sku: str
    on_hand: int
    reserved: int
    available: int

    @classmethod
    def of(cls, item: StockItem) -> "StockLevel":
        return cls(variant_id=item.variant_id, sku=item.sku, on_hand=item.on_hand,
                   reserved=item.reserved, available=item.available)


class StockUpdate(BaseModel):
    on_hand: int = Field(ge=0, le=1_000_000)


@app.get("/health")
def health():
    return {"status": "ok", "service": "inventory"}


@app.get("/api/v1/inventory/availability")
def availability(variant_ids: str = Query(...), db: Session = Depends(get_db)):
    """How many of each variant a shopper can buy right now. Unknown ids are left out."""
    items = db.scalars(select(StockItem).where(StockItem.variant_id.in_(parse_ids(variant_ids)))).all()
    return {"results": [Availability(variant_id=i.variant_id, available=i.available if i.active else 0) for i in items]}


@app.get("/api/v1/inventory/stock")
def stock_levels(variant_ids: str = Query(...), user: CurrentUser = Depends(seller_or_admin),
                 db: Session = Depends(get_db)):
    query = select(StockItem).where(StockItem.variant_id.in_(parse_ids(variant_ids)))
    if user.role != "admin":
        query = query.where(StockItem.seller_id == user.id)  # a seller only sees their own
    return {"results": [StockLevel.of(item) for item in db.scalars(query).all()]}


@app.put("/api/v1/inventory/stock/{variant_id}")
def set_stock(variant_id: uuid.UUID, body: StockUpdate, user: CurrentUser = Depends(seller_or_admin),
              db: Session = Depends(get_db)):
    item = db.get(StockItem, variant_id, with_for_update=True)
    if item is not None and user.role != "admin" and item.seller_id != user.id:
        item = None  # someone else's variant: answer as if it didn't exist
    if item is None:
        # A brand-new option reaches this service a moment after the product is saved
        # (through the catalogue events), so the storefront retries this.
        return JSONResponse(status_code=404, content={
            "code": "not_ready", "detail": "This option is still being set up. Try again in a moment."})
    if body.on_hand < item.reserved:
        db.rollback()
        return JSONResponse(status_code=409, content={
            "code": "below_held",
            "detail": f"{item.reserved} of these are held in customers' checkouts, so stock can't go below {item.reserved}.",
            "reserved": item.reserved,
        })
    item.on_hand = body.on_hand
    db.commit()
    return StockLevel.of(item)
