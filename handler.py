import base64
import copy
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


COMFY_HOST = os.environ.get("COMFY_HOST", "127.0.0.1:8188")
COMFY_BASE_URL = f"http://{COMFY_HOST}"
COMFY_STARTUP_TIMEOUT_SECONDS = int(os.environ.get("COMFY_STARTUP_TIMEOUT_SECONDS", "1800"))
WORKFLOW_TIMEOUT_SECONDS = int(os.environ.get("WORKFLOW_TIMEOUT_SECONDS", "2400"))
WORKFLOW_PATH = Path(__file__).resolve().parent / "workflows" / "api" / "music3.json"

ALLOWED_VOCALS = {
    "female vocals",
    "male vocals",
    "duet",
    "instrumental",
    "auto (decide from idea)",
}
ALLOWED_LANGUAGES = {
    "English",
    "Chinese (Mandarin)",
    "Korean",
    "Japanese",
    "auto",
}


class WorkerError(RuntimeError):
    pass


def _json_request(path, method="GET", payload=None, timeout=30):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{COMFY_BASE_URL}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise WorkerError(f"ComfyUI HTTP {exc.code}: {body[:4000]}") from exc


def wait_for_comfyui():
    deadline = time.monotonic() + COMFY_STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            _json_request("/system_stats", timeout=5)
            return
        except (OSError, WorkerError, json.JSONDecodeError):
            time.sleep(2)
    log_tail = ""
    log_path = Path("/tmp/comfyui.log")
    if log_path.exists():
        log_tail = "\n".join(log_path.read_text(errors="replace").splitlines()[-80:])
    raise WorkerError(f"ComfyUI não iniciou em {COMFY_STARTUP_TIMEOUT_SECONDS}s.\n{log_tail}")


def validate_input(job_input):
    if not isinstance(job_input, dict):
        raise WorkerError("input deve ser um objeto JSON")

    idea = str(job_input.get("idea") or job_input.get("prompt") or "").strip()
    caption = str(job_input.get("caption", "")).strip()
    lyrics = str(job_input.get("lyrics", "")).strip()
    if not idea and not (caption and lyrics):
        raise WorkerError("Informe idea ou caption+lyrics")

    duration = float(job_input.get("duration_seconds", 60))
    if not 30 <= duration <= 300:
        raise WorkerError("duration_seconds deve estar entre 30 e 300")

    vocals = str(job_input.get("vocals", "female vocals"))
    if vocals not in ALLOWED_VOCALS:
        raise WorkerError(f"vocals inválido: {vocals}")

    language = str(job_input.get("language", "English"))
    if language not in ALLOWED_LANGUAGES:
        raise WorkerError(f"language inválido: {language}")

    seed = int(job_input.get("seed", 0))
    if not 0 <= seed <= 0xFFFFFFFF:
        raise WorkerError("seed deve estar entre 0 e 4294967295")

    max_duration = float(job_input.get("max_duration_seconds", duration * 1.5))
    max_duration = min(300.0, max(duration, max_duration))

    return {
        "idea": idea,
        "caption": caption,
        "lyrics": lyrics,
        "genre": str(job_input.get("genre", "")).strip(),
        "vocals": vocals,
        "language": language,
        "duration": duration,
        "max_duration": max_duration,
        "seed": seed,
        "temperature": float(job_input.get("temperature", 0.8)),
        "top_p": float(job_input.get("top_p", 0.95)),
    }


def build_workflow(job_input):
    values = validate_input(job_input)
    workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))

    planner = workflow["55"]["inputs"]
    planner.update(
        {
            "idea": values["idea"],
            "genre_hint": values["genre"],
            "vocal_config": values["vocals"],
            "language": values["language"],
            "duration_seconds": values["duration"],
            "seed": values["seed"],
            "temperature": values["temperature"],
            "top_p": values["top_p"],
        }
    )

    encoder = workflow["45"]["inputs"]
    encoder["seed"] = values["seed"]
    encoder["max_duration"] = values["max_duration"]
    workflow["50"]["inputs"]["seed"] = values["seed"]

    if values["caption"] and values["lyrics"]:
        encoder["caption"] = values["caption"]
        encoder["lyrics"] = values["lyrics"]
        workflow["90"]["inputs"]["caption"] = values["caption"]
        workflow["90"]["inputs"]["lyrics"] = values["lyrics"]
        workflow["90"]["inputs"]["debug"] = json.dumps({"planner": "bypassed"})
        del workflow["55"]

    return workflow, values


def queue_workflow(workflow):
    response = _json_request("/prompt", method="POST", payload={"prompt": workflow})
    prompt_id = response.get("prompt_id")
    if not prompt_id:
        raise WorkerError(f"ComfyUI rejeitou o workflow: {json.dumps(response)[:4000]}")
    return prompt_id


def wait_for_history(prompt_id):
    deadline = time.monotonic() + WORKFLOW_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        history = _json_request(f"/history/{prompt_id}", timeout=30)
        if prompt_id in history:
            result = history[prompt_id]
            status = result.get("status", {})
            if status.get("status_str") == "error":
                raise WorkerError(f"Falha no workflow: {json.dumps(status)[:6000]}")
            if result.get("outputs"):
                return result
        time.sleep(2)
    raise WorkerError(f"Workflow excedeu {WORKFLOW_TIMEOUT_SECONDS}s")


def fetch_output_file(file_info):
    query = urllib.parse.urlencode(
        {
            "filename": file_info["filename"],
            "subfolder": file_info.get("subfolder", ""),
            "type": file_info.get("type", "output"),
        }
    )
    with urllib.request.urlopen(f"{COMFY_BASE_URL}/view?{query}", timeout=120) as response:
        return response.read()


def parse_result(history, values):
    outputs = history.get("outputs", {})
    audio_info = None
    metadata = {}
    for output in outputs.values():
        if output.get("audio") and audio_info is None:
            audio_info = output["audio"][0]
        if output.get("music3_metadata"):
            metadata = copy.deepcopy(output["music3_metadata"][0])

    if audio_info is None:
        raise WorkerError(f"Workflow terminou sem áudio: {json.dumps(outputs)[:4000]}")

    audio_bytes = fetch_output_file(audio_info)
    return {
        "audio": base64.b64encode(audio_bytes).decode("ascii"),
        "audio_mime_type": "audio/mpeg",
        "audio_filename": audio_info["filename"],
        "audio_size_bytes": len(audio_bytes),
        "caption": metadata.get("caption", values["caption"]),
        "lyrics": metadata.get("lyrics", values["lyrics"]),
        "planner_debug": metadata.get("debug"),
        "seed": values["seed"],
        "target_duration_seconds": values["duration"],
        "max_duration_seconds": values["max_duration"],
    }


def handler(job):
    try:
        workflow, values = build_workflow(job.get("input"))
        wait_for_comfyui()
        prompt_id = queue_workflow(workflow)
        history = wait_for_history(prompt_id)
        return parse_result(history, values)
    except Exception as exc:
        return {"error": str(exc), "error_type": type(exc).__name__}


if __name__ == "__main__":
    import runpod

    runpod.serverless.start({"handler": handler})
