"""Runs the frontend's JS unit tests (frontend/tests, node --test + jsdom) as part of pytest.

Skipped when Node or the JS dev dependencies are missing: run `npm install` once to enable them.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(
    shutil.which("node") is None or not (ROOT / "node_modules" / "jsdom").exists(),
    reason="needs Node and `npm install` (jsdom)",
)
def test_frontend_js_unit_tests():
    tests = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "frontend" / "tests").glob("*.test.mjs"))
    result = subprocess.run(["node", "--test", *tests], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
