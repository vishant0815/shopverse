"""The three events the storefront sends. Anything else is refused.

The shapes match the events board in the design canvas. A user id is never accepted from the
body: it comes from the signed-in shopper's token (see auth.py), so extra fields are refused.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

MAX_BATCH = 100
MAX_QUERY_LENGTH = 200


class _Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    occurred_at: AwareDatetime
    # The browser's anonymous id, kept in localStorage. Not linked to an IP address or device.
    session_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9-]+$")


class ProductView(_Event):
    type: Literal["product_view"]
    product_id: UUID
    source: Literal["search", "category", "direct"]


class SearchEvent(_Event):
    type: Literal["search"]
    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
    result_count: int = Field(ge=0)


class AddToCart(_Event):
    type: Literal["add_to_cart"]
    product_id: UUID
    variant_id: UUID
    quantity: int = Field(ge=1, le=99)


ClickEvent = Annotated[ProductView | SearchEvent | AddToCart, Field(discriminator="type")]


class EventBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[ClickEvent] = Field(min_length=1, max_length=MAX_BATCH)
