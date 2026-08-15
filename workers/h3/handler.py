import base64
import json
import math
import os
import re
import tempfile
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


COMFY_HOST = os.environ.get("COMFY_HOST", "127.0.0.1:8188")
COMFY_BASE_URL = f"http://{COMFY_HOST}"
COMFY_STARTUP_TIMEOUT_SECONDS = int(os.environ.get("COMFY_STARTUP_TIMEOUT_SECONDS", "1800"))
WORKFLOW_TIMEOUT_SECONDS = int(os.environ.get("WORKFLOW_TIMEOUT_SECONDS", "3600"))
HANDLER_LOG_PATH = Path(os.environ.get("HANDLER_LOG_PATH", "/runpod-volume/logs/h3-handler-latest.log"))
COMFY_LOG_PATH = Path(os.environ.get("COMFY_LOG_PATH", "/runpod-volume/logs/h3-comfyui-latest.log"))
COMFY_INPUT_DIR = Path(os.environ.get("COMFY_INPUT_DIR", "/comfyui/input"))
COMFY_OUTPUT_DIR = Path(os.environ.get("COMFY_OUTPUT_DIR", "/comfyui/output"))

FPS = 24
MIN_DURATION_SECONDS = 5.0
MAX_DURATION_SECONDS = 15.0
DEFAULT_WIDTH = 864
DEFAULT_HEIGHT = 480
PREVIEW_PIXELS = DEFAULT_WIDTH * DEFAULT_HEIGHT
MAX_PIXELS = 768 * 1344
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_AUDIO_BYTES = 50 * 1024 * 1024
MAX_VIDEO_BYTES = 100 * 1024 * 1024
MAX_REF_VIDEOS = 3
MAX_REF_IMAGES = 3
ASPECT_RATIOS = {"21:9": 21 / 9, "16:9": 16 / 9, "4:3": 4 / 3, "1:1": 1.0, "3:4": 3 / 4, "9:16": 9 / 16}

UNET_NAME = "minimax_h3_ref2va_int8_convrot.safetensors"
TEXT_ENCODER_NAME = "qwen3vl_32b_minimax_h3_int8_convrot.safetensors"
VIDEO_VAE_NAME = "minimax_h3_video_vae_fp16.safetensors"
AUDIO_VAE_NAME = "minimax_h3_audio_vae_fp32.safetensors"
LORA_NAME = "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"


class WorkerError(RuntimeError):
    pass


def log_progress(message):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {message}"
    print(f"worker-h3: {line}", flush=True)
    try:
        HANDLER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with HANDLER_LOG_PATH.open("a", encoding="utf-8") as log_file:
            log_file.write(f"{line}\n")
    except OSError:
        pass


def bootstrap_models():
    from src.bootstrap_models import main
    main()


def _decode_media(value, field_name, max_bytes):
    if not isinstance(value, str) or not value.strip():
        raise WorkerError(f"{field_name} deve ser base64 ou data URI")
    raw_value = value.strip()
    mime_type = ""
    if raw_value.startswith("data:"):
        match = re.fullmatch(r"data:([^;,]+);base64,(.+)", raw_value, re.DOTALL)
        if not match:
            raise WorkerError(f"{field_name} contém data URI inválida")
        mime_type, encoded = match.groups()
    else:
        encoded = raw_value
    try:
        payload = base64.b64decode(re.sub(r"\s+", "", encoded), validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise WorkerError(f"{field_name} contém base64 inválido") from exc
    if not payload or len(payload) > max_bytes:
        raise WorkerError(f"{field_name} vazio ou acima do limite")
    return payload, mime_type.lower()


def _detect_image(payload):
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if payload.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return ".webp", "image/webp"
    raise WorkerError("image deve ser PNG, JPEG ou WebP")


def _detect_audio(payload):
    if payload.startswith(b"ID3") or payload[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}:
        return ".mp3", "audio/mpeg"
    if payload.startswith(b"RIFF") and payload[8:12] == b"WAVE":
        return ".wav", "audio/wav"
    if payload.startswith(b"fLaC"):
        return ".flac", "audio/flac"
    if payload.startswith(b"OggS"):
        return ".ogg", "audio/ogg"
    if len(payload) >= 12 and payload[4:8] == b"ftyp":
        return ".m4a", "audio/mp4"
    raise WorkerError("audio deve ser MP3, WAV, FLAC, OGG ou M4A")


def _detect_video(payload):
    if len(payload) >= 12 and payload[4:8] == b"ftyp":
        return ".mp4", "video/mp4"
    if payload.startswith(b"\x1a\x45\xdf\xa3"):
        return ".webm", "video/webm"
    raise WorkerError("ref_videos deve conter MP4 ou WebM")


def _decode_ref_images(job_input):
    """image é <Picture 1>; ref_images acrescenta <Picture 2> e <Picture 3> na ordem enviada."""
    payload, _ = _decode_media(job_input.get("image"), "image", MAX_IMAGE_BYTES)
    suffix, mime = _detect_image(payload)
    images = [{"bytes": payload, "suffix": suffix, "mime_type": mime}]
    raw = job_input.get("ref_images") or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raise WorkerError("ref_images deve ser uma lista de base64")
    if len(images) + len(raw) > MAX_REF_IMAGES:
        raise WorkerError(f"image + ref_images aceita no máximo {MAX_REF_IMAGES} imagens")
    for index, item in enumerate(raw):
        extra, _ = _decode_media(item, f"ref_images[{index}]", MAX_IMAGE_BYTES)
        extra_suffix, extra_mime = _detect_image(extra)
        images.append({"bytes": extra, "suffix": extra_suffix, "mime_type": extra_mime})
    return images


def _decode_ref_videos(job_input):
    raw = job_input.get("ref_videos") or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raise WorkerError("ref_videos deve ser uma lista de base64")
    if len(raw) > MAX_REF_VIDEOS:
        raise WorkerError(f"ref_videos aceita no máximo {MAX_REF_VIDEOS} vídeos")
    videos = []
    for index, item in enumerate(raw):
        payload, _ = _decode_media(item, f"ref_videos[{index}]", MAX_VIDEO_BYTES)
        suffix, mime = _detect_video(payload)
        videos.append({"bytes": payload, "suffix": suffix, "mime_type": mime})
    return videos


def align_frame_count(duration_seconds):
    frame_count = max(5, round(duration_seconds * FPS))
    while frame_count % 17 != 5:
        frame_count += 1
    return frame_count


def _round32(value):
    return max(32, round(value / 32) * 32)


def resolve_dimensions(job_input):
    width_value, height_value = job_input.get("width"), job_input.get("height")
    if width_value is not None or height_value is not None:
        if width_value is None or height_value is None:
            raise WorkerError("width e height devem ser enviados juntos")
        width, height = _round32(int(width_value)), _round32(int(height_value))
        if width < 256 or height < 256 or width > 2048 or height > 2048:
            raise WorkerError("width e height devem ficar entre 256 e 2048")
        if width * height > MAX_PIXELS:
            raise WorkerError(f"resolução excede {MAX_PIXELS} pixels")
        return width, height
    aspect = str(job_input.get("aspect") or job_input.get("aspect_ratio") or "16:9")
    if aspect not in ASPECT_RATIOS:
        raise WorkerError(f"aspect inválido: {aspect}")
    ratio = ASPECT_RATIOS[aspect]
    return _round32(math.sqrt(PREVIEW_PIXELS * ratio)), _round32(math.sqrt(PREVIEW_PIXELS / ratio))


def validate_input(job_input):
    if not isinstance(job_input, dict):
        raise WorkerError("input deve ser um objeto JSON")
    prompt = str(job_input.get("prompt") or "").strip()
    if not prompt or len(prompt) > 40000:
        raise WorkerError("prompt é obrigatório e deve ter até 40000 caracteres")
    ref_images = _decode_ref_images(job_input)
    image_bytes = ref_images[0]["bytes"]
    image_suffix, image_mime = ref_images[0]["suffix"], ref_images[0]["mime_type"]
    audio_bytes, _ = _decode_media(job_input.get("audio"), "audio", MAX_AUDIO_BYTES)
    audio_suffix, audio_mime = _detect_audio(audio_bytes)
    try:
        duration = float(job_input.get("duration_seconds", 8))
        seed = int(job_input.get("seed", 0))
    except (TypeError, ValueError) as exc:
        raise WorkerError("duration_seconds e seed inválidos") from exc
    if not math.isfinite(duration) or not MIN_DURATION_SECONDS <= duration <= MAX_DURATION_SECONDS:
        raise WorkerError("duration_seconds deve estar entre 5 e 15")
    if not 0 <= seed <= 0xFFFFFFFFFFFFFFFF:
        raise WorkerError("seed fora do intervalo uint64")
    width, height = resolve_dimensions(job_input)
    frame_count = align_frame_count(duration)
    ref_videos = _decode_ref_videos(job_input)
    if "<Picture 1>" not in prompt or "<Audio 1>" not in prompt:
        prompt = "Use <Picture 1> como referência visual e <Audio 1> como referência de voz, ritmo e música.\n\n" + prompt
    return {
        "prompt": prompt, "duration": duration, "frame_count": frame_count,
        "generated_duration": frame_count / FPS, "seed": seed, "width": width, "height": height,
        "image_bytes": image_bytes, "image_suffix": image_suffix, "image_mime_type": image_mime,
        "audio_bytes": audio_bytes, "audio_suffix": audio_suffix, "audio_mime_type": audio_mime,
        "ref_videos": ref_videos, "ref_images": ref_images,
    }


def prepare_input_files(values):
    token = f"h3-{uuid.uuid4().hex}"
    directory = COMFY_INPUT_DIR / token
    directory.mkdir(parents=True, exist_ok=False)
    audio_path = directory / f"reference{values['audio_suffix']}"
    audio_path.write_bytes(values["audio_bytes"])
    image_names = []
    for index, image in enumerate(values["ref_images"]):
        path = directory / f"reference_{index}{image['suffix']}"
        path.write_bytes(image["bytes"])
        image_names.append(f"{token}/{path.name}")
    video_names = []
    for index, video in enumerate(values.get("ref_videos") or []):
        video_path = directory / f"ref_video_{index}{video['suffix']}"
        video_path.write_bytes(video["bytes"])
        video_names.append(f"{token}/{video_path.name}")
    return {
        "directory": directory,
        "image_name": image_names[0],
        "image_names": image_names,
        "audio_name": f"{token}/{audio_path.name}",
        "video_names": video_names,
    }


def cleanup_input_files(input_files):
    if not input_files:
        return
    for child in input_files["directory"].iterdir():
        child.unlink(missing_ok=True)
    input_files["directory"].rmdir()


def build_workflow(values, image_name, audio_name, video_names=None, image_names=None):
    workflow = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": UNET_NAME, "weight_dtype": "default"}},
        "2": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": LORA_NAME, "strength_model": 0.7}},
        "3": {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": ["2", 0], "shift_video": 12.0, "shift_audio": 6.0}},
        "4": {"class_type": "CLIPLoader", "inputs": {"clip_name": TEXT_ENCODER_NAME, "type": "minimax", "device": "default"}},
        "5": {"class_type": "VAELoader", "inputs": {"vae_name": VIDEO_VAE_NAME}},
        "6": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE_NAME}},
        "7": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "8": {"class_type": "LoadAudio", "inputs": {"audio": audio_name}},
        "9": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
            "clip": ["4", 0], "vae": ["5", 0], "audio_vae": ["6", 0], "prompt": values["prompt"],
            "width": values["width"], "height": values["height"], "length": values["frame_count"],
            "ref_image_size": "match", "ref_images.ref_image_0": ["7", 0], "ref_audios.ref_audio_0": ["8", 0]}},
        "10": {"class_type": "BasicScheduler", "inputs": {"model": ["3", 0], "scheduler": "beta", "steps": 4, "denoise": 1.0}},
        "11": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "12": {"class_type": "RandomNoise", "inputs": {"noise_seed": values["seed"]}},
        "13": {"class_type": "BasicGuider", "inputs": {"model": ["3", 0], "conditioning": ["9", 0]}},
        "14": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["12", 0], "guider": ["13", 0], "sampler": ["11", 0], "sigmas": ["10", 0], "latent_image": ["9", 1]}},
        "15": {"class_type": "VAEDecode", "inputs": {"samples": ["14", 0], "vae": ["5", 0]}},
        "17": {"class_type": "CreateVideo", "inputs": {"images": ["15", 0], "fps": 24.0, "bit_depth": 8}},
        "18": {"class_type": "SaveVideo", "inputs": {"video": ["17", 0], "filename_prefix": "h3-preview/preview", "format": "mp4", "codec": "auto"}},
    }
    # imagens extras viram <Picture 2>/<Picture 3> na ordem enviada
    for index, name in enumerate((image_names or [])[1:], start=1):
        load_id = str(200 + index)
        workflow[load_id] = {"class_type": "LoadImage", "inputs": {"image": name}}
        workflow["9"]["inputs"][f"ref_images.ref_image_{index}"] = [load_id, 0]
    # ref_videos entram como frames (LoadVideo -> GetVideoComponents); a trilha
    # deles é descartada de propósito, o áudio de referência é o do input.
    for index, name in enumerate(video_names or []):
        load_id, components_id = str(100 + index * 2), str(101 + index * 2)
        workflow[load_id] = {"class_type": "LoadVideo", "inputs": {"file": name}}
        workflow[components_id] = {"class_type": "GetVideoComponents", "inputs": {"video": [load_id, 0]}}
        workflow["9"]["inputs"][f"ref_videos.ref_video_{index}"] = [components_id, 0]
    return workflow


def _json_request(path, method="GET", payload=None, timeout=30):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{COMFY_BASE_URL}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise WorkerError(f"ComfyUI HTTP {exc.code}: {body[:6000]}") from exc


def _comfy_log_tail():
    if not COMFY_LOG_PATH.exists():
        return ""
    return "\n".join(COMFY_LOG_PATH.read_text(errors="replace").splitlines()[-100:])


def ensure_comfyui_alive():
    pid_path = Path("/tmp/comfyui.pid")
    if not pid_path.exists():
        return
    try:
        os.kill(int(pid_path.read_text(encoding="utf-8").strip()), 0)
    except (ProcessLookupError, ValueError) as exc:
        raise WorkerError(f"ComfyUI encerrou inesperadamente.\n{_comfy_log_tail()}") from exc


def wait_for_comfyui():
    deadline = time.monotonic() + COMFY_STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        ensure_comfyui_alive()
        try:
            _json_request("/system_stats", timeout=5)
            return
        except (OSError, WorkerError, json.JSONDecodeError):
            time.sleep(2)
    raise WorkerError(f"ComfyUI não iniciou em {COMFY_STARTUP_TIMEOUT_SECONDS}s.\n{_comfy_log_tail()}")


def queue_workflow(workflow):
    response = _json_request("/prompt", method="POST", payload={"prompt": workflow})
    prompt_id = response.get("prompt_id")
    if not prompt_id:
        raise WorkerError(f"ComfyUI rejeitou o workflow: {json.dumps(response)[:6000]}")
    return prompt_id


def wait_for_history(prompt_id):
    deadline = time.monotonic() + WORKFLOW_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        ensure_comfyui_alive()
        history = _json_request(f"/history/{prompt_id}", timeout=30)
        if prompt_id in history:
            result = history[prompt_id]
            status = result.get("status", {})
            if status.get("status_str") == "error":
                raise WorkerError(f"Falha no workflow: {json.dumps(status)[:8000]}")
            if result.get("outputs"):
                return result
        time.sleep(2)
    raise WorkerError(f"Workflow excedeu {WORKFLOW_TIMEOUT_SECONDS}s")


def _find_video_info(value):
    if isinstance(value, dict):
        filename = value.get("filename")
        if isinstance(filename, str) and filename.lower().endswith(".mp4"):
            return value
        for nested in value.values():
            found = _find_video_info(nested)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_video_info(nested)
            if found:
                return found
    return None


def _safe_output_path(file_info):
    output_root = COMFY_OUTPUT_DIR.resolve()
    candidate = (output_root / file_info.get("subfolder", "") / file_info["filename"]).resolve()
    if candidate != output_root and output_root not in candidate.parents:
        raise WorkerError("Caminho de saída inválido retornado pelo ComfyUI")
    return candidate


def fetch_output_file(file_info):
    output_path = _safe_output_path(file_info)
    if output_path.is_file():
        return output_path.read_bytes(), output_path
    query = urllib.parse.urlencode({
        "filename": file_info["filename"], "subfolder": file_info.get("subfolder", ""),
        "type": file_info.get("type", "output"),
    })
    with urllib.request.urlopen(f"{COMFY_BASE_URL}/view?{query}", timeout=300) as response:
        return response.read(), None


def probe_video(video_path):
    if video_path is None:
        return {}
    process = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
         "-of", "json", str(video_path)],
        check=True, capture_output=True, text=True, timeout=120,
    )
    return json.loads(process.stdout)


def mux_original_audio(video_bytes, video_path, values):
    with tempfile.TemporaryDirectory(prefix="h3-mux-") as temp_directory:
        temp_root = Path(temp_directory)
        source_video_path = video_path
        if source_video_path is None:
            source_video_path = temp_root / "generated.mp4"
            source_video_path.write_bytes(video_bytes)
        audio_path = temp_root / f"original{values['audio_suffix']}"
        output_path = temp_root / "final.mp4"
        audio_path.write_bytes(values["audio_bytes"])
        process = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(source_video_path), "-i", str(audio_path),
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k", "-ac", "2",
                "-t", f"{values['generated_duration']:.6f}",
                "-movflags", "+faststart", str(output_path),
            ],
            check=True, capture_output=True, text=True, timeout=300,
        )
        if process.stderr:
            log_progress(f"ffmpeg_mux={process.stderr[-2000:]}")
        return output_path.read_bytes(), probe_video(output_path)


def parse_result(history, values):
    video_info = _find_video_info(history.get("outputs", {}))
    if video_info is None:
        raise WorkerError(f"Workflow terminou sem MP4: {json.dumps(history.get('outputs', {}))[:6000]}")
    generated_video_bytes, video_path = fetch_output_file(video_info)
    video_bytes, probe = mux_original_audio(generated_video_bytes, video_path, values)
    streams = probe.get("streams", [])
    return {
        "video": base64.b64encode(video_bytes).decode("ascii"),
        "video_mime_type": "video/mp4", "video_filename": video_info["filename"],
        "video_size_bytes": len(video_bytes),
        "duration_seconds": float(probe.get("format", {}).get("duration", 0) or 0),
        "has_video": any(stream.get("codec_type") == "video" for stream in streams),
        "has_audio": any(stream.get("codec_type") == "audio" for stream in streams),
        "streams": streams, "seed": values["seed"], "width": values["width"],
        "height": values["height"], "fps": FPS, "frame_count": values["frame_count"],
        "requested_duration_seconds": values["duration"],
        "generated_duration_seconds": values["generated_duration"],
        "audio_source": "input",
        "ref_video_count": len(values.get("ref_videos") or []),
        "ref_image_count": len(values.get("ref_images") or []),
    }


def handler(job):
    job_id = job.get("id", "unknown")
    started_at = time.monotonic()
    input_files = None
    log_progress(f"job={job_id} etapa=validar_input inicio")
    values = validate_input(job.get("input"))
    log_progress(f"job={job_id} etapa=bootstrap inicio")
    bootstrap_models()
    log_progress(f"job={job_id} etapa=bootstrap concluida")
    wait_for_comfyui()
    log_progress(f"job={job_id} etapa=comfyui_pronto")
    try:
        input_files = prepare_input_files(values)
        workflow = build_workflow(
            values, input_files["image_name"], input_files["audio_name"],
            input_files["video_names"], input_files["image_names"],
        )
        prompt_id = queue_workflow(workflow)
        log_progress(f"job={job_id} etapa=workflow_enfileirado prompt_id={prompt_id}")
        history = wait_for_history(prompt_id)
        log_progress(f"job={job_id} etapa=workflow_concluido")
        result = parse_result(history, values)
        log_progress(
            f"job={job_id} etapa=resultado_concluido elapsed={time.monotonic() - started_at:.1f}s "
            f"bytes={result['video_size_bytes']}"
        )
        return result
    finally:
        cleanup_input_files(input_files)


if __name__ == "__main__":
    import runpod
    runpod.serverless.start({"handler": handler})
