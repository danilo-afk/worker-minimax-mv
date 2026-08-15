# RunPod Music 3

## Runtime decisions

- GPU: RTX 4090 or another NVIDIA GPU with at least 24 GB VRAM.
- Workers: minimum `0`, maximum `1` while validating.
- Network volume: 50 GB minimum, mounted by RunPod at `/runpod-volume`.
- Execution timeout: 40 minutes for first boot plus model downloads.
- Idle timeout: 5 seconds after validation to avoid idle charges.

The image contains code only. The handler becomes ready before model bootstrap,
matching the proven RunPod pattern used by the older workers. The first job
downloads approximately 22 GiB of pinned model files to the network volume and
validates both exact byte size and SHA-256. Later workers reuse marker-validated
files without hashing them again.

## Exact model profile

The default follows the paid workflow guidance rather than the conflicting UI
widget labels:

- Music 3 DiT FP16;
- pruned Music 3 text encoder INT8 ConvRot;
- Music 3 DAV VAE;
- Qwen3-VL 4B BF16 for the planner;
- Euler, 30 steps, CFG 1.7;
- planner temperature 0.8 and top-p 0.95;
- generation ceiling equal to 150% of the writing target.

## Build

Pushes to `main` publish two GHCR tags:

- `ghcr.io/danilo-afk/worker-minimax-mv:music3`;
- `ghcr.io/danilo-afk/worker-minimax-mv:music3-<full-git-sha>`.

RunPod templates should use the immutable SHA tag after the first successful
build. The moving `music3` tag is only for initial bootstrap.

## Provisioned resources

- Network volume: `8uo5w5b3cc` (`US-IL-1`, 50 GB).
- Serverless endpoint: `slpzigher2zxw8`.
- Workers: minimum `0`, maximum `1`.
- GPU priority: RTX 4090, RTX 6000 Ada, L40S.
- Duration: `0.04` to `360` seconds, matching the pinned ComfyUI node.

## Direct validation

Submit `test_input.json` to the endpoint's `/run` API and poll `/status/{job}`.
A valid result must contain:

- non-empty base64 MP3 data;
- `audio_size_bytes` greater than zero;
- generated `caption` and `lyrics`;
- `max_duration_seconds` equal to 1.5 times the target unless overridden;
- no workflow validation or missing-node errors.

Download the returned MP3 and verify it with `ffprobe`. Listen to the beginning,
middle and ending; a successful job alone does not prove that the outro was not
cut.
