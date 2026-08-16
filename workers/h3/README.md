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
    "height": 480,
    "ref_images": ["data:image/png;base64,..."],
    "ref_image_size": "match",
    "anchor_image": "data:image/png;base64,...",
    "anchor_frame_idx": 0,
    "ref_videos": ["data:video/mp4;base64,...", "..."]
  }
}
```

Também aceita `aspect`: `21:9`, `16:9`, `4:3`, `1:1`, `3:4` ou `9:16`. Duração: 5–15 segundos, alinhada à grade temporal `17k+5`.

`image` é sempre `<Picture 1>`. `ref_images` acrescenta `<Picture 2>` e `<Picture 3>` na ordem enviada (3 imagens no total, como no workflow do autor). Use a primeira para a identidade do rosto — um retrato frontal e nítido — e as seguintes para cenário, figurino e demais personagens: com o rosto pequeno ou de perfil na referência, o modelo inventa traços.

`ref_image_size` aceita `match` (padrão, reduz cada referência à área da geração) ou `max` (borda curta de 2048 do pipeline de referência, melhor fidelidade de identidade e amostragem mais lenta). Como o nó só reduz e nunca amplia, o peso de identidade de cada personagem é proporcional à resolução da referência enviada: amplie retratos pequenos antes de enviar ou o personagem perde traços marcantes.

`anchor_image` ancora um frame REAL do vídeo via `MiniMaxH3AddGuide` (`anchor_frame_idx`, negativo conta do fim). É diferente de `ref_images`/`ref_videos`, que são referência estilística: a âncora faz o clipe **começar** naquele frame. Para encadear blocos, passe o último frame do bloco anterior como `anchor_image` — usar o tail como `ref_video` faz a pose do bloco anterior dominar a descrição e a cena derivar a cada elo.

`ref_videos` é opcional (até 3, MP4 ou WebM) e entra como referência de estilo/movimento via `LoadVideo` → `GetVideoComponents`. A trilha desses vídeos é descartada: o áudio de referência e a trilha final continuam sendo o `audio` do input.

**Fatie os `ref_videos` antes de enviar.** O nó não trunca referência de áudio nem reduz vídeo abaixo do canvas: um clipe 720x1280 de 192 frames é reescalado para `768x1344` e, somados três, superam em tokens latentes a própria geração — caminho direto para OOM na H100. Envie clipes curtos (~39 frames) e pequenos (ex.: `384x672`, abaixo do teto de `768*1344` pixels, para o nó preservar a resolução enviada).

**O `audio` deve ter exatamente a duração do clipe** (`frame_count / 24`). O nó encoda `ref_audios` inteiro, sem truncar ao vídeo — áudio mais longo que a geração desalinha o lip-sync.

Teste sem GPU: `cd workers/h3 && python -m unittest discover -s tests -v`.

Imagem publicada: `ghcr.io/danilo-afk/worker-minimax-mv:h3-<sha>`.
