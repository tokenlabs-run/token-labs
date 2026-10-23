"""Build PR #62938 with cached native extensions, then install into /runtime."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import tarfile
import urllib.request
import zipfile

COMMIT = "aed08d76a682f1475957c0730ea1f5ecb150fda0"
CACHE = Path("/model-cache/flint-vllm-pr") / COMMIT
CACHE.mkdir(parents=True, exist_ok=True)
wheel_dir = CACHE / "wheels"
wheel_dir.mkdir(exist_ok=True)
wheels = list(wheel_dir.glob("vllm-*.whl"))
if not wheels:
    archive = CACHE / "source.tar.gz"
    if not archive.exists():
        temporary = CACHE / "source.tar.gz.partial"
        urllib.request.urlretrieve(
            f"https://codeload.github.com/WoosukKwon/vllm/tar.gz/{COMMIT}", temporary
        )
        temporary.replace(archive)
    source_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
    if source_sha256 != "ea9623a1b0cf3b6e1863e5f63e1c1356998cee8a7682a9811e284cd05faa8e3d":
        raise RuntimeError(f"Unexpected PR source archive SHA256: {source_sha256}")
    print("Source archive SHA256:", source_sha256, flush=True)
    build = Path("/tmp/flint-vllm-build")
    build.mkdir(exist_ok=True)
    with tarfile.open(archive) as source:
        source.extractall(build, filter="data")
    checkout = build / f"vllm-{COMMIT}"
    # This PR changes Python/JIT code. Use vLLM's supported precompiled build
    # mode with the native extensions from the digest-pinned ARM64 base image.
    distribution = importlib.metadata.distribution("vllm")
    native_wheel = build / "base-native.whl"
    with zipfile.ZipFile(native_wheel, "w", compression=zipfile.ZIP_STORED) as output:
        for entry in distribution.files:
            if str(entry).startswith("vllm/") and ".pyc" not in str(entry):
                file = distribution.locate_file(entry)
                if file.is_file():
                    output.write(file, str(entry))
    subprocess.run([
        "python3", "-m", "pip", "install", "--disable-pip-version-check",
        "setuptools-rust==1.12.0", "wheel==0.45.1",
    ], check=True)
    env = dict(os.environ,
        VLLM_USE_PRECOMPILED="1",
        VLLM_PRECOMPILED_WHEEL_LOCATION=str(native_wheel),
        SETUPTOOLS_SCM_PRETEND_VERSION="0.32.0.dev0+pr62938.aed08d76",
        VLLM_USE_RUST_FRONTEND="0",
    )
    subprocess.run([
        "python3", "-m", "pip", "wheel", "--no-build-isolation", "--no-deps",
        "--wheel-dir", str(wheel_dir), str(checkout),
    ], env=env, check=True)
    wheels = list(wheel_dir.glob("vllm-*.whl"))
if len(wheels) != 1:
    raise RuntimeError(f"Expected exactly one PR wheel, got {wheels}")
subprocess.run([
    "python3", "-m", "pip", "install", "--no-deps", "--no-compile",
    "--target", "/runtime/site-packages", str(wheels[0]), "gguf==0.19.0",
], check=True)
Path("/runtime/source.json").write_text(json.dumps({
    "repository": "WoosukKwon/vllm", "commit": COMMIT,
    "wheel_sha256": hashlib.sha256(wheels[0].read_bytes()).hexdigest(),
    "native_base_image": "sha256:5641d14b70c991f8b78c3a5baf0281cb73dbd2ea69932dd6a328820f420ec4bc",
}) + "\n")
print(Path("/runtime/source.json").read_text(), flush=True)
