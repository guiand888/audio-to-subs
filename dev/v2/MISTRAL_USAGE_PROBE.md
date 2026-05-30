# Mistral usage probe (M0.5 spike — blocks M2)

`audio_to_subs/core/cost.py` needs to know whether `mistralai==2.4.5`'s `audio.transcriptions.complete` response surfaces usage information (billed seconds / tokens / cost) — and if so, under which field names.

Until that's verified, **`core/cost.py` uses the duration-× -rate fallback only**. The fallback is correct but imprecise: it doesn't account for any silence-skipping or model-side accounting the API may do.

## Why this is its own milestone

Running it against the live API costs money (a few cents) and requires a working `MISTRAL_API_KEY`. It's a one-off; once the answer is known, the script can be discarded and `cost.py`'s field accesses are pinned to real names.

## Probe script (one-off, not committed long-term)

Drop this at `scripts/probe_mistral_usage.py`; do **not** include it in the v2.0 source distribution.

```python
"""Probe the shape of mistralai==2.4.5's transcription response.

Usage:
    MISTRAL_API_KEY=... python scripts/probe_mistral_usage.py path/to/short.wav
"""
import json
import os
import pprint
import sys

from mistralai.client import Mistral

def dump(obj, prefix=""):
    print(f"\n--- {prefix} ---")
    if hasattr(obj, "model_dump"):
        pprint.pprint(obj.model_dump())
    else:
        pprint.pprint(vars(obj))

def main(audio_path: str) -> None:
    api_key = os.environ["MISTRAL_API_KEY"]
    client = Mistral(api_key=api_key)
    with open(audio_path, "rb") as f:
        resp = client.audio.transcriptions.complete(
            model="voxtral-mini-latest",
            file=("clip.wav", f, "audio/wav"),
            timestamp_granularities=["segment"],
        )
    dump(resp, "response")
    for attr in ("usage", "metadata", "billing", "stats"):
        val = getattr(resp, attr, None)
        if val is not None:
            dump(val, f"response.{attr}")
    print("\n--- raw JSON-ish dump ---")
    try:
        print(json.dumps(resp.model_dump(), indent=2, default=str))
    except Exception as e:
        print(f"model_dump failed: {e}")
        print(dir(resp))

if __name__ == "__main__":
    main(sys.argv[1])
```

Run against a short clip (~10 s) to keep cost negligible.

## What to record below after running

Fill in this section in the same commit that runs the probe, then commit.

### Result (TBD — fill in after running)

- [ ] Response object has a `usage` attribute: **yes / no**
- [ ] If yes: fields present (list them):
  - `usage.<field_name>`: type, semantics, example value
  - …
- [ ] Total cost in USD is reported directly: **yes / no**
- [ ] Billed duration in seconds is reported directly: **yes / no**
- [ ] Other surprising fields:
- [ ] Raw `model_dump()` output (truncate to ~30 lines):
  ```
  …
  ```

### Decision for `core/cost.py`

Based on the result above, pick one:

- [ ] **Path A — Mistral provides usage**: `extract_usage(response)` returns the relevant dict; `compute_cost` reads `usage.<field>` and computes USD. Fallback path retained only for the case where the SDK changes shape.
- [ ] **Path B — Mistral does NOT provide usable usage**: `extract_usage(response)` returns `None`; `compute_cost` always uses `audio_duration_seconds / 60 × rate_usd_per_minute`. `mistral_usage_json` on the job row stays NULL.

### Reference once decided

Update `core/cost.py` docstring and `dev/v2/PIPELINE_CHANGES.md` §4 to reference the exact field names this probe identified.
