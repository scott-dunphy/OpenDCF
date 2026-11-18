import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).parents[1] / "fixtures" / "appraisals"


def test_public_published_software_fixture_catalog_is_complete_and_untampered():
    catalog = json.loads((ROOT / "manifests" / "catalog.json").read_text())
    assert catalog["schema_version"] == "1.0.0"
    assert len(catalog["sources"]) >= 5
    for entry in catalog["sources"]:
        source = ROOT / "source" / entry["filename"]
        assert source.is_file(), entry["id"]
        content = source.read_bytes()
        assert len(content) == entry["byte_size"]
        assert hashlib.sha256(content).hexdigest() == entry["sha256"]
        assert entry["source_url"].startswith("https://www.sec.gov/Archives/")
        assert entry["software_evidence"]
        assert entry["coverage"]


def test_fixture_names_and_ids_are_unique():
    catalog = json.loads((ROOT / "manifests" / "catalog.json").read_text())
    ids = [entry["id"] for entry in catalog["sources"]]
    names = [entry["filename"] for entry in catalog["sources"]]
    assert len(ids) == len(set(ids))
    assert len(names) == len(set(names))
