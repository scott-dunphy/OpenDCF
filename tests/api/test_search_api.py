"""API tests for the command-palette search endpoint."""
from httpx import AsyncClient

from src.api.search import router as search_router
from src.main import app

# Until the router is registered in src/api/router.py, mount it on the test app (once).
if not any(getattr(r, "path", None) == "/api/v1/search" for r in app.routes):
    app.include_router(search_router)


async def _property(client: AsyncClient, name: str, **extra) -> str:
    resp = await client.post("/api/v1/properties", json={
        "name": name, "property_type": "office", "total_area": "10000", "area_unit": "sf",
        "analysis_start_date": "2025-01-01", "city": "Austin", "state": "TX", **extra,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _search(client: AsyncClient, q: str, **params) -> list[dict]:
    resp = await client.get("/api/v1/search", params={"q": q, **params})
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestSearch:
    async def test_empty_query_returns_nothing(self, client: AsyncClient):
        await _property(client, "Harbor Point")
        assert await _search(client, "") == []
        assert await _search(client, "   ") == []

    async def test_mixed_results_with_links(self, client: AsyncClient):
        prop_id = await _property(client, "Harbor Point")
        val = await client.post(f"/api/v1/properties/{prop_id}/valuations", json={
            "name": "Harbor base case", "discount_rate": "0.08", "exit_cap_rate": "0.065",
        })
        tenant = await client.post(f"/api/v1/valuations/{val.json()['id']}/tenants", json={"name": "Harbor Freight"})

        results = await _search(client, "HARBOR")
        by_kind = {r["kind"]: r for r in results}
        assert set(by_kind) == {"property", "valuation", "tenant"}

        assert by_kind["property"] == {
            "kind": "property", "id": prop_id, "title": "Harbor Point", "subtitle": "Austin, TX · Office",
            "property_id": prop_id, "href": f"#/property/{prop_id}",
        }
        v = by_kind["valuation"]
        assert v["id"] == val.json()["id"] and v["href"] == f"#/valuation/{v['id']}"
        assert v["subtitle"] == "Harbor Point · draft"
        t = by_kind["tenant"]
        assert t["id"] == tenant.json()["id"] and t["subtitle"] == "Harbor Point"
        assert t["href"] == f"#/property/{prop_id}"

    async def test_tenant_in_several_valuations_is_one_result(self, client: AsyncClient):
        """Each valuation has its own tenant rows; search lists a tenant once per property."""
        prop_id = await _property(client, "Lease Linked")
        val = await client.post(f"/api/v1/properties/{prop_id}/valuations", json={
            "name": "Base", "discount_rate": "0.08", "exit_cap_rate": "0.065",
        })
        await client.post(f"/api/v1/valuations/{val.json()['id']}/tenants", json={"name": "Zephyr Labs"})
        copy = await client.post(f"/api/v1/valuations/{val.json()['id']}/duplicate")
        assert copy.status_code == 201, copy.text
        assert len((await client.get(f"/api/v1/valuations/{copy.json()['id']}/tenants")).json()) == 1

        [hit] = await _search(client, "zephyr")
        assert hit["kind"] == "tenant" and hit["property_id"] == prop_id

    async def test_prefix_and_word_start_rank_first(self, client: AsyncClient):
        await _property(client, "Midtown Plaza")       # substring "town" mid-word
        await _property(client, "Old Town Center")     # word-start
        await _property(client, "Towne Square")        # prefix
        titles = [r["title"] for r in await _search(client, "town")]
        assert titles == ["Towne Square", "Old Town Center", "Midtown Plaza"]

    async def test_excludes_intake_properties(self, client: AsyncClient):
        await _property(client, "Intake Tower", external_id="__appraisal_intake__:abc")
        await _property(client, "Real Tower")
        assert [r["title"] for r in await _search(client, "tower")] == ["Real Tower"]

    async def test_limit(self, client: AsyncClient):
        for i in range(5):
            await _property(client, f"Cedar {i}")
        assert len(await _search(client, "cedar", limit=3)) == 3
        resp = await client.get("/api/v1/search", params={"q": "cedar", "limit": 0})
        assert resp.status_code == 422


class TestSearchWildcards:
    async def test_underscore_and_percent_match_literally(self, client: AsyncClient):
        plain = await _property(client, "Plain Tower")
        under = await _property(client, "North_Wing")
        pct = await _property(client, "100% Leased Plaza")
        plain_val = await client.post(f"/api/v1/properties/{plain}/valuations", json={
            "name": "Plain base", "discount_rate": "0.08", "exit_cap_rate": "0.065",
        })
        await client.post(f"/api/v1/valuations/{plain_val.json()['id']}/tenants", json={"name": "Acme Corp"})

        assert [r["id"] for r in await _search(client, "_")] == [under]
        assert [r["id"] for r in await _search(client, "%")] == [pct]
        assert await _search(client, "\\") == []
