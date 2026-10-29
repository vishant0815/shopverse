"""The HTTP client that talks to the product service."""

from decimal import Decimal

import httpx
import pytest

from ordering import catalog


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code, self._payload = status_code, payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def test_parses_prices_as_decimal(monkeypatch):
    payload = {"results": [{"variant_id": "abc", "price": "19.99"}]}
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(payload=payload))

    result = catalog.lookup_variants(["abc"])

    assert result["abc"]["price"] == Decimal("19.99")


def test_sends_each_id_once(monkeypatch):
    seen = {}

    def fake_get(url, params, timeout):
        seen["ids"] = params["ids"]
        return FakeResponse(payload={"results": []})

    monkeypatch.setattr(httpx, "get", fake_get)
    catalog.lookup_variants(["a", "b", "a"])

    assert seen["ids"] == "a,b"


def test_no_ids_means_no_request(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: pytest.fail("should not be called"))

    assert catalog.lookup_variants([]) == {}


@pytest.mark.parametrize("failure", [
    lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down")),
    lambda *a, **k: (_ for _ in ()).throw(httpx.ReadTimeout("slow")),
    lambda *a, **k: FakeResponse(status_code=500, payload={}),
    lambda *a, **k: FakeResponse(payload=None),
    lambda *a, **k: FakeResponse(payload={"unexpected": True}),
])
def test_failures_become_catalog_unavailable(monkeypatch, failure):
    monkeypatch.setattr(httpx, "get", failure)

    with pytest.raises(catalog.CatalogUnavailable):
        catalog.lookup_variants(["abc"])
