# MiniMax H3 R2V preview worker

Worker RunPod Serverless isolado para previews MiniMax H3 Reference-to-Video com áudio nativo.

## Preset do workflow de referência

- ComfyUI core: `7fe8a6138504f90ff7be82f3babf416da32876b1`
- padrão: `864x480`, `8s`, `192` frames a `24fps`; suporta até `15s`/`362` frames dentro da faixa treinada
- sigma shift: vídeo `12`, áudio `6`
- Euler + Beta, `4` passos, LoRA oficial com força `0.7`
- sem SeedVR, LTX, FILM ou custom nodes
- áudio final preservado do input Music3, sem reprocessamento pelo H3

Pesos oficiais pinados:

- `Comfy-Org/MiniMax-H3@d07f69bc8fa09c9717e1e47180034f9322e0e54d`
- `lightx2v/Minimax-h3-Turbo@5d1d4829fe614c1b93fcfd9cc7718e9ba71f73e1`

O bootstrap persiste aproximadamente 69 GB no network volume com marcadores `.sha256-ok`. Recomenda-se volume de pelo menos 100 GB.

## Contrato

```json
{
  "input": {
    "image": "data:image/png;base64,...",
    "audio": "data:audio/mpeg;base64,...",
    "prompt": "Use <Picture 1> para a cantora e <Audio 1> para a música...",
    "duration_seconds": 8,
    "seed": 3877326292,
    "width": 864,
    "height": 480
  }
}
```

Também aceita `aspect`: `21:9`, `16:9`, `4:3`, `1:1`, `3:4` ou `9:16`. Duração: 5–15 segundos, alinhada à grade temporal `17k+5`.

Teste sem GPU: `cd workers/h3 && python -m unittest discover -s tests -v`.

Imagem publicada: `ghcr.io/danilo-afk/worker-minimax-mv:h3-<sha>`.
