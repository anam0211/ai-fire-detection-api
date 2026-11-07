"""Copy an explicit allowlist into AI_Fire_Detection_Handoff and verify the original model."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "AI_Fire_Detection_Handoff"
FILES = (
    "api.py", "model.joblib", "model.sha256", "requirements.txt", "requirements-dev.txt",
    ".python-version", ".env.example", ".gitignore", ".gitattributes", ".dockerignore", "render.yaml", "pytest.ini",
    "README.md", "API_DOCUMENTATION.md", "INTEGRATION_GUIDE.md", "ENVIRONMENT_VARIABLES.md",
    "TEST_REPORT.md", "train_fire_ai_colab.ipynb", "example_normal_SIMULATED.csv",
    "tests/test_api.py", "scripts/smoke_test.py", "scripts/verify_local.py", "scripts/build_handoff.py",
    "examples/dashboard_fetch.js", "examples/esp32_http_https/esp32_http_https.ino",
    "examples/esp32_http_https/secrets.example.h",
    "openapi.json", "WEB_INTEGRATION.md", "scripts/build_web_handoff.py",
    "web_client/ai-client.mjs", "web_client/example.mjs", "web_client/verify.mjs",
    "web_client/.env.example", "web_client/ai-api.postman_collection.json",
    "web_client/local.postman_environment.json",
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if ROOT.name == "AI_Fire_Detection_Handoff":
        raise RuntimeError("Run the packaging script from the source project, not from the handoff copy")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_web_handoff.py")], check=True)
    expected = (ROOT / "model.sha256").read_text(encoding="utf-8").split()[0]
    if digest(ROOT / "model.joblib") != expected:
        raise RuntimeError("Original model SHA-256 changed; packaging aborted")
    for name in FILES:
        if not (ROOT / name).is_file():
            raise FileNotFoundError(f"Missing handoff input: {name}")
    if DESTINATION.exists():
        unexpected = [p.relative_to(DESTINATION).as_posix() for p in DESTINATION.rglob("*")
                      if p.is_file() and p.relative_to(DESTINATION).parts[0] != ".git"
                      and p.relative_to(DESTINATION).as_posix() not in (*FILES, "HANDOFF_MANIFEST.json")]
        if unexpected:
            raise RuntimeError(f"Unexpected handoff files; review them before rebuilding: {unexpected}")
    DESTINATION.mkdir(exist_ok=True)
    for name in FILES:
        source, target = ROOT / name, DESTINATION / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if name == "model.joblib" and target.exists():
            if digest(target) != expected:
                raise RuntimeError("Handoff model differs; refusing to overwrite model.joblib")
            continue
        shutil.copy2(source, target)
    manifest = {"model_sha256": expected, "files": [
        {"path": name, "bytes": (DESTINATION / name).stat().st_size,
         "sha256": digest(DESTINATION / name)} for name in FILES
    ]}
    (DESTINATION / "HANDOFF_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    assert digest(ROOT / "model.joblib") == expected == digest(DESTINATION / "model.joblib")
    archive_path = ROOT / "AI_Fire_API_Render.zip"
    with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
        for name in (*FILES, "HANDOFF_MANIFEST.json"):
            archive.write(DESTINATION / name, name)
    with ZipFile(archive_path) as archive:
        assert set(archive.namelist()) == set(FILES) | {"HANDOFF_MANIFEST.json"}
        assert archive.testzip() is None
        assert hashlib.sha256(archive.read("model.joblib")).hexdigest() == expected
    print(f"Created {DESTINATION.name}: {len(FILES)} allowlisted files plus HANDOFF_MANIFEST.json")
    print(f"Created {archive_path.name}: deployment source with the original model")
    print(f"Original and copied model SHA-256: {expected}")


if __name__ == "__main__":
    main()
