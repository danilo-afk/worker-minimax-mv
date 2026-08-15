import hashlib
import json
import os
from pathlib import Path

from huggingface_hub import hf_hub_download


APP_ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = Path(os.environ.get("MODEL_ROOT", "/runpod-volume/models"))
MANIFEST_PATH = APP_ROOT / "src" / "model_manifest.json"


def ensure_model(model):
    destination = MODEL_ROOT / model["filename"]
    expected_size = model["size_bytes"]
    expected_sha256 = model["sha256"]
    marker = destination.with_suffix(f"{destination.suffix}.sha256-ok")
    if (
        destination.is_file()
        and destination.stat().st_size == expected_size
        and marker.is_file()
        and marker.read_text(encoding="utf-8").strip() == expected_sha256
    ):
        print(f"worker-music3: modelo pronto: {model['filename']}")
        return

    if destination.exists():
        destination.unlink()
    marker.unlink(missing_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)

    print(f"worker-music3: baixando {model['filename']}")
    downloaded = Path(
        hf_hub_download(
            repo_id=model["repo_id"],
            filename=model["filename"],
            revision=model["revision"],
            local_dir=MODEL_ROOT,
        )
    )
    actual_size = downloaded.stat().st_size
    if actual_size != expected_size:
        downloaded.unlink(missing_ok=True)
        raise RuntimeError(
            f"Tamanho inválido para {model['filename']}: {actual_size} != {expected_size}"
        )

    digest = hashlib.sha256()
    with downloaded.open("rb") as model_file:
        for chunk in iter(lambda: model_file.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    actual_sha256 = digest.hexdigest()
    if actual_sha256 != expected_sha256:
        downloaded.unlink(missing_ok=True)
        raise RuntimeError(
            f"SHA-256 inválido para {model['filename']}: "
            f"{actual_sha256} != {expected_sha256}"
        )

    marker.write_text(f"{expected_sha256}\n", encoding="utf-8")
    print(f"worker-music3: download e SHA-256 validados: {model['filename']}")


def main(include_planner=True):
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for model in manifest["models"]:
        if not include_planner and model["filename"].endswith("qwen3vl_4b_bf16.safetensors"):
            continue
        ensure_model(model)


if __name__ == "__main__":
    main()
