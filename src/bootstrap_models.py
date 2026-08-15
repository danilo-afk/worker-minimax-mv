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
    if destination.is_file() and destination.stat().st_size == expected_size:
        print(f"worker-music3: modelo pronto: {model['filename']}")
        return

    if destination.exists():
        destination.unlink()
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
    print(f"worker-music3: download validado: {model['filename']}")


def main():
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for model in manifest["models"]:
        ensure_model(model)


if __name__ == "__main__":
    main()
