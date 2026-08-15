# MiniMax Music 3 worker

Input contract:

```json
{
  "input": {
    "idea": "string",
    "genre": "string",
    "language": "string",
    "vocals": "string",
    "duration_seconds": 60,
    "seed": 0
  }
}
```

Optional fields are `max_duration_seconds`, `temperature`, `top_p`, `caption`
and `lyrics`. Supplying both `caption` and `lyrics` bypasses the planner.

The response contains base64 MP3 audio plus `caption`, `lyrics`, planner debug
metadata, seed and duration values.

Pinned runtime:

- ComfyUI `7fe8a6138504f90ff7be82f3babf416da32876b1`;
- M3 SongPlanner `e46b13b722e460f6e393b917a5a9c289ee51e0c1`;
- MiniMax Music 3 Hugging Face revision `6444666eb6edfb2c7fcab5f8b81da8b84b4b17b6`;
- Qwen3-VL revision `d3f437bd7bd2df08e77c8fe5c51ca4239f753aa3`.
