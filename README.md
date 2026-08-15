# worker-minimax-mv

RunPod Serverless workers for a modular music-video pipeline built around MiniMax Music 3, Krea 2 and MiniMax H3.

## Architecture

The pipeline is intentionally split into independent container images and RunPod endpoints:

1. `music3`: song planning and music generation.
2. `krea2`: consistent multi-view character sheets.
3. `h3`: reference-to-video generation with audio conditioning.

Video upscaling and interpolation will remain optional stages so the main H3 worker does not load every model during cold start.

## Repository layout

```text
workers/
  music3/  MiniMax Music 3 worker
  krea2/   Krea 2 character-sheet worker
  h3/      MiniMax H3 reference-to-video worker
shared/    Reusable RunPod and ComfyUI integration code
workflows/api/  Sanitized ComfyUI API templates
docs/      Architecture and operational notes
```

## Public repository policy

This repository does not contain:

- paid or private third-party workflow archives;
- original Patreon workflow files;
- model checkpoints;
- API keys or RunPod credentials;
- generated media.

Only independently adapted API templates and original integration code may be committed.

## Status

Initial scaffold. The first implementation target is the MiniMax Music 3 worker.
