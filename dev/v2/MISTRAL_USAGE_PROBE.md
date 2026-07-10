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

### Result

Probe executed successfully on 2026-06-02 against `mistralai==2.4.5` with model `voxtral-mini-latest` and a 10-second WAV audio clip.

- [x] Response object has a `usage` attribute: **yes**
- [x] If yes: fields present (list them):
  - `usage.prompt_tokens`: int, number of prompt tokens (example: 4)
  - `usage.completion_tokens`: int, number of completion/generated tokens (example: 87)
  - `usage.total_tokens`: int, sum of prompt + completion tokens (example: 466)
  - `usage.prompt_audio_seconds`: int, billed audio duration in seconds (example: 9)
  - `usage.prompt_tokens_details`: dict, breakdown with `audio_tokens` (int) and `cached_tokens` (int)
- [x] Total cost in USD is reported directly: **no**
- [x] Billed duration in seconds is reported directly: **yes** (`prompt_audio_seconds`)
- [x] Other surprising fields: `finish_reason` (null in successful response), `language` (null when not detected)
- [x] Raw `model_dump()` output (truncate to ~30 lines):
  ```json
  {
    "model": "voxtral-mini-latest",
    "text": "The first time you've had a boy over. I mean, I'm bound to be a little surprised, but I'm not gonna embarrass you. I better go charge the camcorder. I'm kidding! Come on!",
    "usage": {
      "prompt_tokens": 4,
      "completion_tokens": 87,
      "total_tokens": 466,
      "prompt_audio_seconds": 9,
      "prompt_tokens_details": {
        "cached_tokens": 0,
        "audio_tokens": 375
      }
    },
    "language": null,
    "segments": [...],
    "finish_reason": null
  }
  ```

### Decision for `core/cost.py`

- [x] **Path A — Mistral provides usage**: `extract_usage(response)` returns the relevant dict; `compute_cost` reads `usage.prompt_audio_seconds` for billed duration and optionally `usage.total_tokens` for token-based pricing. Fallback path retained only for the case where the SDK changes shape.
- [ ] **Path B — Mistral does NOT provide usable usage**: `extract_usage(response)` returns `None`; `compute_cost` always uses `audio_duration_seconds / 60 × rate_usd_per_minute`. `mistral_usage_json` on the job row stays NULL.

### Reference once decided

Update `core/cost.py` docstring and `dev/v2/PIPELINE_CHANGES.md` §4 to reference the exact field names this probe identified.

## Note for M5.7

This probe's `main()` function (above) is a reusable template for a *different*, still-open question blocking `M5.7` (`MILESTONES.md`): `transcription_client.py`'s `_call_mistral_transcription`/`_call_mistral_transcription_with_timestamps` build a `kwargs` dict and splat it into `complete(...)`, which mypy rejects because several SDK params (e.g. `language`) default to a distinct `Unset()` sentinel rather than `None`. This probe's own working call never passes `language` at all, so it doesn't settle whether passing `language=None` explicitly (as a straightforward `**kwargs`-free rewrite would) is equivalent to omitting it on the wire, or whether it changes request behavior.

A follow-up probe adapted from this script should specifically:
- Call `complete(...)` once with `language` omitted and once with `language=None` explicitly, and diff the raw request/response to confirm they're identical (or aren't).
- Try the tuple-based `file=("clip.wav", f, "audio/wav")` form used above instead of building a `File(...)` object — if the SDK accepts it identically, it may sidestep the `fileName`/`contentType` alias mismatch in `transcription_client.py` entirely, rather than just fixing the keyword casing.

Same cost/setup caveats as above (a few cents, needs `MISTRAL_API_KEY`, short clip).

### Resolution (M5.7, 2026-07-10)

Both open questions are now settled against the live Mistral API:

- **`language` omitted vs `language=None`:** a `language`-omitted call and an
  explicit `language=None` call return equivalent transcripts/usage, so passing
  `UNSET` (which omits the field on the wire) when no language is set is
  behavior-preserving and safe. `transcription_client.py` passes `UNSET` (not
  `None`) for this reason; see the comment above
  `_call_mistral_transcription`.
- **`File(...)` object vs tuple form:** the `File(...)` constructor (with
  `file_name`/`content_type`) is already type-correct against
  `Transcriptions.complete` and serializes correctly on the wire, so the tuple
  form is unnecessary. The calls were rewritten with explicit, typed kwargs
  (no `**kwargs` splat) to satisfy mypy --strict, and verified live for both
  `_call_mistral_transcription` and `_call_mistral_transcription_with_timestamps`.
