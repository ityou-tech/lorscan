"""BazaarAdapter.crawl_set walks listing pages then fetches detail pages."""

from __future__ import annotations

from pathlib import Path

import httpx
import respx

from lorscan.services.marketplaces.bazaarofmagic import BazaarAdapter

FIXTURE_DIR = Path(__file__).parents[3] / "fixtures" / "marketplaces" / "bazaarofmagic"


async def test_crawl_set_yields_listings():
    listing_html = (FIXTURE_DIR / "listing.html").read_text()
    detail_html = (FIXTURE_DIR / "detail.html").read_text()
    empty_html = (FIXTURE_DIR / "empty_listing.html").read_text()

    base = "https://www.bazaarofmagic.eu"
    adapter = BazaarAdapter(inter_batch_delay_s=0.0)  # no delay in tests

    with respx.mock(assert_all_called=False) as mock:
        mock.get(
            f"{base}/nl-NL/c/rise-of-the-floodborn/1000676",
            params={"page": "1", "items": "24"},
        ).mock(return_value=httpx.Response(200, text=listing_html))
        mock.get(
            f"{base}/nl-NL/c/rise-of-the-floodborn/1000676",
            params={"page": "2", "items": "24"},
        ).mock(return_value=httpx.Response(200, text=empty_html))
        mock.get(url__regex=rf"{base}/nl-NL/p/.+").mock(
            return_value=httpx.Response(200, text=detail_html)
        )

        async with httpx.AsyncClient(base_url=base, timeout=10.0) as client:
            listings = []
            async for listing in adapter.crawl_set(
                client,
                set_code="ROF",
                category_path="/nl-NL/c/rise-of-the-floodborn/1000676",
            ):
                listings.append(listing)

    # Each of the 24 listing cards on page 1 should yield one Listing.
    # Page 2 returns empty, terminating the loop.
    assert len(listings) == 24, f"expected 24 listings, got {len(listings)}"

    # Every listing has a populated url + title + price + currency.
    sample = listings[0]
    assert sample.url.startswith(f"{base}/nl-NL/p/")
    assert sample.title
    assert sample.price_cents > 0
    assert sample.currency == "EUR"

    # The detail page is the Pinocchio fixture (in-stock, foil, #224).
    # Since respx returns it for every detail request, all 24 listings
    # share those extras.
    assert sample.in_stock is True
    assert sample.finish == "foil"
    assert sample.collector_number == "224"


async def test_crawl_set_terminates_on_empty_page_one():
    """If page 1 itself is empty, generator yields nothing and stops."""
    base = "https://www.bazaarofmagic.eu"
    empty_html = (FIXTURE_DIR / "empty_listing.html").read_text()
    adapter = BazaarAdapter(inter_batch_delay_s=0.0)

    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=rf"{base}/nl-NL/c/.+").mock(
            return_value=httpx.Response(200, text=empty_html)
        )

        async with httpx.AsyncClient(base_url=base) as client:
            listings = [
                listing
                async for listing in adapter.crawl_set(
                    client,
                    set_code="ROF",
                    category_path="/nl-NL/c/rise-of-the-floodborn/1000676",
                )
            ]

    assert listings == []


async def test_crawl_set_yields_listings_in_face_of_per_detail_failures():
    """If one detail fetch 500s, the affected listing is dropped silently
    but other listings still arrive."""
    listing_html = (FIXTURE_DIR / "listing.html").read_text()
    detail_html = (FIXTURE_DIR / "detail.html").read_text()
    empty_html = (FIXTURE_DIR / "empty_listing.html").read_text()
    base = "https://www.bazaarofmagic.eu"
    adapter = BazaarAdapter(inter_batch_delay_s=0.0)

    with respx.mock(assert_all_called=False) as mock:
        mock.get(
            f"{base}/nl-NL/c/rise-of-the-floodborn/1000676",
            params={"page": "1", "items": "24"},
        ).mock(return_value=httpx.Response(200, text=listing_html))
        mock.get(
            f"{base}/nl-NL/c/rise-of-the-floodborn/1000676",
            params={"page": "2", "items": "24"},
        ).mock(return_value=httpx.Response(200, text=empty_html))

        # First detail request 500s; rest succeed. We do this by chaining a
        # side-effect counter via respx's calls list.
        call_count = {"n": 0}

        def detail_responder(request):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return httpx.Response(500, text="boom")
            return httpx.Response(200, text=detail_html)

        mock.get(url__regex=rf"{base}/nl-NL/p/.+").mock(side_effect=detail_responder)

        async with httpx.AsyncClient(base_url=base) as client:
            listings = [
                listing
                async for listing in adapter.crawl_set(
                    client,
                    set_code="ROF",
                    category_path="/nl-NL/c/rise-of-the-floodborn/1000676",
                )
            ]

    # 24 listings on page 1, one detail fetch failed → 23 yielded.
    assert len(listings) == 23


def test_bazaar_adapter_satisfies_shop_adapter_protocol():
    from lorscan.services.marketplaces.base import ShopAdapter

    assert isinstance(BazaarAdapter(), ShopAdapter)
