# MiniMax Music 3 worker

Planned input contract:

```json
{
  "input": {
    "idea": "string",
    "genre": "string",
    "language": "string",
    "vocals": "string",
    "duration_seconds": 120,
    "seed": 0
  }
}
```

The worker will return generated audio plus sanitized planner metadata such as caption and lyrics.
