# v2 — Pipeline changes

The existing pipeline modules under `audio_to_subs/core/` (relocated from `src/` in M0) stay the source of truth for transcription. v2 adds three things on top:

1. A **cancellation token** plumbed through `Pipeline` and `audio_extractor`.
2. An optional **structured progress callback**, alongside the existing 2-arg `(message, percentage)` one used by the CLI.
3. A **cost module** that extracts usage from the Mistral response (with a duration × rate fallback).

No backwards-incompatible changes. The CLI keeps using the legacy callback and ignores the structured one.

## 1. Cancellation — `audio_to_subs/core/cancel.py`

```python
import threading

class Cancelled(Exception):
    """Raised when a CancelToken has been set."""


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def set(self) -> None:
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self._event.is_set():
            raise Cancelled
```

### Wiring

- `Pipeline.__init__` gains `cancel_token: CancelToken | None = None`. Stored as `self._cancel`.
- `Pipeline._transcribe_audio_segments` calls `self._cancel.check()` at the top of every segment loop iteration.
- `Pipeline.process_video` calls `self._cancel.check()` between stages (after extract, after split, after transcribe, before generate).
- `audio_to_subs/core/audio_extractor.extract_audio(..., cancel_token=None)`:
  - In the FFmpeg progress loop, after each `_parse_ffmpeg_progress(...)` call, check the token.
  - On cancel: `process.terminate()` followed by `process.wait(timeout=2)`; raise `Cancelled`. Clean up any partial output file in the caller (`finally` block already deletes temps).
- `audio_to_subs/core/audio_splitter.split_audio(..., cancel_token=None)`: same pattern — check before each split, terminate FFmpeg on cancel.
- `audio_to_subs/core/transcription_client.TranscriptionClient` does **not** take a token. Mistral SDK calls are synchronous and uncancellable from the outside; the worker simply doesn't observe cancel until the current Mistral call returns. Document this in the docstring.

## 2. Structured progress callback

Existing callback signature stays:

```python
ProgressCallback = Callable[[str, Optional[int]], None]
```

Add a parallel optional one:

```python
from typing import TypedDict, Literal

class ProgressEvent(TypedDict, total=False):
    stage: Literal["extract", "split", "transcribe", "generate", "init", "done"]
    percent: int
    message: str
    segment_index: int
    segment_count: int
    audio_duration_seconds: float
    mistral_usage: dict       # raw dict from Mistral response (when available)

StructuredProgressCallback = Callable[[ProgressEvent], None]
```

`Pipeline.__init__` gains:

```python
def __init__(
    self,
    api_key: str,
    progress_callback: ProgressCallback | None = None,
    *,
    structured_progress_callback: StructuredProgressCallback | None = None,
    cancel_token: CancelToken | None = None,
    temp_dir: str | None = None,
    transcription_model: str = "voxtral-mini-latest",
    language: str | None = None,
    verbose_progress: bool = False,
) -> None: ...
```

When emitting progress, `Pipeline` calls both callbacks if both are provided:

```python
def _progress(self, message: str, percentage: int | None, **extra) -> None:
    if self._cb:
        self._cb(message, percentage if self._verbose else None)
    if self._scb:
        self._scb({"message": message, "percent": percentage, **extra})
```

The CLI continues to pass only the legacy callback — zero CLI changes.

## 3. Return value — `PipelineResult`

Today `Pipeline.process_video` returns the output path string. Promote to a small dataclass:

```python
from dataclasses import dataclass

@dataclass
class PipelineResult:
    output_path: str
    audio_duration_seconds: float
    mistral_usage: dict | None
    segments_count: int

    def __fspath__(self) -> str:
        return self.output_path

    def __str__(self) -> str:
        return self.output_path
```

The CLI ignores the return value today, so it continues to work. The worker reads `result.audio_duration_seconds` and `result.mistral_usage` to persist them on the job row.

`audio_duration_seconds` is already known — `audio_to_subs.core.audio_splitter.get_audio_duration(audio_path)` exposes it; `Pipeline` computes it once after extract.

`mistral_usage` comes from `core/cost.py` (see below). It is `None` if the Mistral SDK doesn't surface a usage field.

`segments_count` is the number of transcription segments yielded — same value used in progress percentages today.

## 4. Cost — `audio_to_subs/core/cost.py`

```python
from dataclasses import dataclass
from typing import Any

@dataclass
class CostBreakdown:
    audio_duration_seconds: float
    usage: dict | None         # raw usage dict if present
    estimated_cost_usd: float
    source: Literal["mistral_usage", "duration_fallback"]


def extract_usage(mistral_response: Any) -> dict | None:
    """Return the response's `usage` field as a plain dict, or None.

    Verified shape: TBD — see dev/v2/MISTRAL_USAGE_PROBE.md.
    """
    # Try common SDK shapes:
    for attr in ("usage", "model_dump"):
        val = getattr(mistral_response, attr, None)
        if callable(val):
            try:
                dumped = val()
                if isinstance(dumped, dict) and "usage" in dumped:
                    return dumped["usage"]
            except Exception:
                pass
        elif val is not None and hasattr(val, "model_dump"):
            return val.model_dump()
        elif isinstance(val, dict):
            return val
    return None


def compute_cost(
    *,
    audio_duration_seconds: float,
    mistral_usage: dict | None,
    rate_usd_per_minute: float,
) -> CostBreakdown:
    if mistral_usage:
        # If Mistral returns a billed-duration or billed-tokens field, use it.
        # Implementation depends on the probe; document the exact field accessed here.
        duration_min = mistral_usage.get("billed_duration_seconds")
        if duration_min is not None:
            cost = (duration_min / 60.0) * rate_usd_per_minute
            return CostBreakdown(
                audio_duration_seconds=audio_duration_seconds,
                usage=mistral_usage,
                estimated_cost_usd=cost,
                source="mistral_usage",
            )
    # Fallback: pure duration × rate
    cost = (audio_duration_seconds / 60.0) * rate_usd_per_minute
    return CostBreakdown(
        audio_duration_seconds=audio_duration_seconds,
        usage=mistral_usage,
        estimated_cost_usd=cost,
        source="duration_fallback",
    )
```

The exact field names accessed inside `extract_usage`/`compute_cost` come from the probe documented in `MISTRAL_USAGE_PROBE.md`. Until that runs, the fallback path is the default and is correct.

## What stays the same

- `audio_extractor.extract_audio` — same signature plus new `cancel_token` kwarg (default `None`, fully backwards-compatible).
- `audio_splitter.split_audio` / `needs_splitting` / `get_audio_duration` — only `split_audio` gains a `cancel_token` kwarg.
- `transcription_client.TranscriptionClient` — no signature change. The worker reads usage from the response separately via `core/cost.py`.
- `subtitle_generator.SubtitleGenerator` — unchanged.
- `config_parser.ConfigParser` — unchanged. Used only by CLI batch mode.
- `logging_config.configure_logging` — unchanged.

## Worker integration sketch

```python
# audio_to_subs/worker/runner.py
def run_job(claimed: ClaimedJob, deps: WorkerDeps) -> None:
    token = CancelToken()
    bridge = ProgressBridge(deps, claimed.id, token)
    pipeline = Pipeline(
        api_key=deps.mistral_api_key,
        structured_progress_callback=bridge.on_event,
        cancel_token=token,
        transcription_model=deps.settings.mistral_model,
        language=claimed.language_code,
    )
    try:
        result = pipeline.process_video(
            claimed.media_path,
            claimed.output_path,
            output_format=claimed.output_format,
        )
    except Cancelled:
        persist_cancelled(deps.db, claimed.id)
        publish_done(deps.redis, claimed.id, status="cancelled")
        return
    except Exception as e:
        persist_failed(deps.db, claimed.id, error_message=str(e))
        publish_done(deps.redis, claimed.id, status="failed", error=str(e))
        return

    cost = compute_cost(
        audio_duration_seconds=result.audio_duration_seconds,
        mistral_usage=result.mistral_usage,
        rate_usd_per_minute=deps.settings.mistral_rate_usd_per_minute,
    )
    persist_success(deps.db, claimed.id, result, cost)
    publish_done(deps.redis, claimed.id, status="done")
    deps.bazarr.rescan_for(claimed)   # best-effort, stubs OK
```

## Tests

- `tests/test_core_cancel.py` — `Pipeline.process_video` raises `Cancelled` when token set before transcribe; FFmpeg subprocess terminated when token set during extract; partial temp files cleaned.
- `tests/test_core_cost.py` — usage-present path returns `source="mistral_usage"`; usage-absent path returns `source="duration_fallback"`.
- `tests/test_core_pipeline_structured.py` — structured callback receives `stage`/`percent`/`message` and gets the final `done` event with `audio_duration_seconds` and `mistral_usage`. Legacy callback continues to receive `(message, percentage)` tuples in lockstep.
- Existing `tests/test_pipeline.py` continues to pass unchanged — its assertions only touch the legacy callback.
