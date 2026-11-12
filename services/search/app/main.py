"""Search API: product search with facets, and autosuggest.

Read-only. The index is kept up to date by the worker (see worker.py), from catalogue events.
"""

import logging
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Literal

from elastic_transport import ConnectionError as TransportConnectionError
from elastic_transport import ConnectionTimeout
from elasticsearch import ApiError, Elasticsearch
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from .config import get_settings
from .index import ensure_index
from .search import search_products, suggest_products

log = logging.getLogger("search.api")

SortOrder = Literal["relevance", "price_asc", "price_desc", "newest"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.es = Elasticsearch(settings.es_url)
    try:
        ensure_index(app.state.es, settings.search_index)
    except Exception as exc:
        # The worker creates the index too, so the API can start before Elasticsearch is up.
        log.warning("search index not ready yet (%s)", exc)
    yield
    app.state.es.close()


app = FastAPI(title="Shopverse search service", docs_url="/api/v1/search/docs",
              openapi_url="/api/v1/search/openapi.json", lifespan=lifespan)


def es_client(request: Request) -> Elasticsearch:
    return request.app.state.es


def unavailable(exc: Exception) -> HTTPException:
    log.warning("search unavailable: %s", exc)
    return HTTPException(status_code=503, detail="Search is temporarily unavailable. Try again in a moment.")


@app.get("/health")
def health(es: Elasticsearch = Depends(es_client)):
    try:
        alive = es.ping()
    except (TransportConnectionError, ConnectionTimeout, ApiError):
        alive = False
    if not alive:
        return JSONResponse(status_code=503, content={"status": "unavailable", "service": "search"})
    return {"status": "ok", "service": "search"}


@app.get("/api/v1/search/products")
def products(
    q: str = Query("", max_length=100),
    category: str | None = Query(None, max_length=100),
    colour: str | None = Query(None, max_length=50),
    size: str | None = Query(None, max_length=20),
    min_price: Decimal | None = Query(None, ge=0, le=1_000_000),
    max_price: Decimal | None = Query(None, ge=0, le=1_000_000),
    sort: SortOrder = "relevance",
    page: int = Query(1, ge=1, le=200),
    page_size: int = Query(24, ge=1, le=48),
    es: Elasticsearch = Depends(es_client),
):
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(status_code=400, detail="min_price can't be more than max_price.")
    try:
        return search_products(
            es, get_settings().search_index, q=q.strip(), category=category, colour=colour, size=size,
            min_price=min_price, max_price=max_price, sort=sort, page=page, page_size=page_size,
        )
    except (TransportConnectionError, ConnectionTimeout, ApiError) as exc:
        raise unavailable(exc) from exc


@app.get("/api/v1/search/suggest")
def suggest(q: str = Query("", max_length=100), es: Elasticsearch = Depends(es_client)):
    text = q.strip()
    if not text:
        return {"results": []}
    try:
        return {"results": suggest_products(es, get_settings().search_index, text)}
    except (TransportConnectionError, ConnectionTimeout, ApiError) as exc:
        raise unavailable(exc) from exc
