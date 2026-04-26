"""Listing dataclass + ShopAdapter Protocol surface."""

from __future__ import annotations

from lorscan.services.marketplaces.base import Listing, ShopAdapter


def test_listing_is_frozen():
    listing = Listing(
        external_id="9154978",
        title="Pinocchio, Strings Attached (#224) (foil)",
        price_cents=1500,
        currency="EUR",
        in_stock=True,
        url="https://www.bazaarofmagic.eu/nl-NL/p/pinocchio-strings-attached-224-foil/9154978",
        finish="foil",
        collector_number="224",
    )
    try:
        listing.price_cents = 999  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("Expected Listing to be frozen")


def test_shop_adapter_is_a_protocol():
    # Any duck-typed object with the right attributes should satisfy isinstance.
    class FakeAdapter:
        slug = "fake"
        display_name = "Fake Shop"

        async def crawl_set(self, client, set_code, category_path):
            yield Listing(
                external_id="x",
                title="x",
                price_cents=0,
                currency="EUR",
                in_stock=False,
                url="x",
                finish=None,
                collector_number=None,
            )

    assert isinstance(FakeAdapter(), ShopAdapter)
