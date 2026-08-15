# Architecture

## Pipeline

```text
idea
  -> MiniMax Music 3
  -> audio analysis and scene segmentation
  -> Krea 2 character sheet
  -> MiniMax H3 clips per audio segment
  -> optional upscale and interpolation
  -> final composition
```

## Deployment boundaries

Each heavyweight model family receives its own Docker image and RunPod endpoint. This keeps cold starts, network-volume requirements and GPU selection independent.

The platform communicates with every endpoint through a small prompt-oriented JSON contract. ComfyUI node IDs and filesystem paths remain private implementation details inside each worker.

## Validation order

1. Convert the UI workflow into ComfyUI API format.
2. Validate the graph against the exact ComfyUI/custom-node image.
3. Run a direct RunPod job with minimal inputs.
4. Validate generated media, duration and audio/video synchronization.
5. Register the endpoint in `platform_k` only after the direct worker test passes.
