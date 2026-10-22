"""Every canonical tool must complete a semantic, real HTTP task lifecycle."""
import io
import time
from urllib.parse import quote

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.tools.registry import all_tools
from app.tools.convert import tesseract_path
from qa.tool_scenarios import SCENARIOS, scenario_files, validate_output


def test_canonical_tool_inventory_has_exactly_one_scenario():
    types = [c["type"] for c in SCENARIOS]
    assert len(types) == len(set(types))
    assert set(types) == {tool.type for tool in all_tools()}


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda c: c["type"])
def test_tool_http_semantic_result(scenario):
    if scenario["type"] == "ocr" and not tesseract_path():
        pytest.skip("Tesseract engine absent: OCR output not verified")
    with TestClient(app) as client:
        ids = []
        for name, data, mime in scenario_files(scenario):
            r = client.post("/api/files/upload", files={"file": (name, data, mime)})
            assert r.status_code == 200, r.text
            info = r.json(); ids.append(info["id"])
            if info.get("passwordProtected"):
                assert client.post(f"/api/files/{info['id']}/password", json={"password":"pool-secret"}).status_code == 200
        r = client.post("/api/tasks", json={"type":scenario["type"],"files":ids,**scenario["params"]})
        assert r.status_code == 200, r.text
        tid = r.json()
        try:
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                r = client.get(f"/api/tasks/{tid}/change"); assert r.status_code == 200
                result = r.json()
                if result["status"] in ("Completed", "Failed"): break
                time.sleep(.05)
            else: pytest.fail("Task exceeded deadline")
            assert result["status"] == "Completed", result
            pattern = result["resultFullUrlPattern"]
            url = "/" + pattern.split("/",1)[1].replace("%7B%7Bfilename%7D%7D", quote(result["resultFilename"]))
            response = client.get(url); assert response.status_code == 200
            assert "no-store" in response.headers["cache-control"]
            assert response.content and len(response.content) == result["resultFileSize"]
            validate_output(scenario, response.content, result["resultFilename"])
            assert client.get(f"/api/tasks/{tid}/download/{quote(result['resultFilename'])}").status_code == 403
        finally:
            assert client.delete(f"/api/tasks/{tid}").status_code == 200
            assert client.get(f"/api/tasks/{tid}/change").status_code == 404
