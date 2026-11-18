"""index.html is served with each local asset URL versioned by a hash of the file's content."""
import re
import shutil

from httpx import AsyncClient

import src.main


def _version(html: str, asset: str) -> str:
    return re.search(rf'"/frontend/{re.escape(asset)}\?v=([0-9a-f]+)"', html).group(1)


async def test_index_versions_local_assets_by_content(client: AsyncClient, tmp_path, monkeypatch):
    r = await client.get("/")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
    assert len(_version(r.text, "app.js")) == 10
    assert _version(r.text, "css/ws1.css")
    assert "https://fonts.googleapis.com" in r.text  # external URLs untouched

    # Editing a file (no restart) changes its version and only its version
    frontend = tmp_path / "frontend"
    shutil.copytree(src.main._frontend_dir, frontend)
    monkeypatch.setattr(src.main, "_frontend_dir", frontend)
    before = (await client.get("/")).text
    with (frontend / "app.js").open("a") as f:
        f.write("\n// edited\n")
    after = (await client.get("/")).text
    assert _version(after, "app.js") != _version(before, "app.js")
    assert _version(after, "style.css") == _version(before, "style.css")
