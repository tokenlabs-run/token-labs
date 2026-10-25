"""Verify public auth, live inventory and installed Codex's catalog parser."""
import json
from pathlib import Path
import subprocess
import tempfile
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from credential import token

URL = "https://api.tokenlabs.run/codex/models?client_version=0.164.0"
for key in (None, "invalid-catalog-test-key"):
    request = Request(URL, headers={} if key is None else {"Authorization": f"Bearer {key}"})
    try:
        urlopen(request, timeout=15).close()
        raise AssertionError("Unauthenticated catalog was accepted")
    except HTTPError as error:
        assert error.code == 401, error.code
with urlopen(Request(URL, headers={"Authorization": "Bearer " + token()}), timeout=15) as response:
    document = json.load(response)
assert any(m["slug"] == "nvidia/Qwen3.6-35B-A3B-NVFP4" for m in document["models"])
with tempfile.TemporaryDirectory(prefix="tokenlabs-catalog-verify-") as tmp:
    path = Path(tmp) / "models.json"
    path.write_text(json.dumps(document))
    result = subprocess.run(["codex", "debug", "models", "-c",
        "model_catalog_json=" + json.dumps(str(path))], capture_output=True, text=True, check=True)
    parsed = json.loads(result.stdout)
    expected = {m["slug"] for m in document["models"]}
    assert {m["slug"] for m in parsed["models"]} == expected
print("PASS: anonymous/wrong key rejected, authenticated catalog and Codex parser agree")
for entry in document["models"]:
    print(entry["slug"], "context_window=" + str(entry["context_window"]))
