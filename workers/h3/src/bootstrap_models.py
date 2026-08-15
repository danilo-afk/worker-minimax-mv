import hashlib
import json
import os
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = Path(os.environ.get("MODEL_ROOT", "/runpod-volume/models"))
MANIFEST_PATH = APP_ROOT / "src" / "model_manifest.json"


def ensure_model(model):
    from huggingface_hub import hf_hub_download

    destination = MODEL_ROOT / model["destination"]
    marker = destination.with_suffix(f"{destination.suffix}.sha256-ok")
    if (
        destination.is_file()
        and destination.stat().st_size == model["size_bytes"]
        and marker.is_file()
        and marker.read_text(encoding="utf-8").strip() == model["sha256"]
    ):
        print(f"worker-h3: modelo pronto: {model['destination']}", flush=True)
        return

    destination.unlink(missing_ok=True)
    marker.unlink(missing_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    downloaded = Path(
        hf_hub_download(
            repo_id=model["repo_id"],
            filename=model["source_filename"],
            revision=model["revision"],
            local_dir=MODEL_ROOT,
        )
    )
    if downloaded != destination:
        destination.unlink(missing_ok=True)
        downloaded.replace(destination)

    actual_size = destination.stat().st_size
    if actual_size != model["size_bytes"]:
        destination.unlink(missing_ok=True)
        raise RuntimeError(
            f"Tamanho inválido para {model['destination']}: "
            f"{actual_size} != {model['size_bytes']}"
        )

    digest = hashlib.sha256()
    with destination.open("rb") as model_file:
        for chunk in iter(lambda: model_file.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != model["sha256"]:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"SHA-256 inválido para {model['destination']}")

    marker.write_text(f"{model['sha256']}\n", encoding="utf-8")
    print(f"worker-h3: modelo validado: {model['destination']}", flush=True)


def main():
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for model in manifest["models"]:
        ensure_model(model)


if __name__ == "__main__":
    main()
