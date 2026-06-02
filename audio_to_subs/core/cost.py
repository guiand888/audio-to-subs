"""Cost computation for Mistral AI transcription.

Extracts usage information from Mistral transcription responses and computes
costs based on configured rates. Supports both duration-based and token-based
billing.

Verified field names from mistralai==2.4.5 with model voxtral-mini-latest:
- usage.prompt_audio_seconds: billed audio duration in seconds
- usage.prompt_tokens: number of prompt tokens
- usage.completion_tokens: number of completion/generated tokens
- usage.total_tokens: sum of prompt + completion tokens
- usage.prompt_tokens_details: dict with audio_tokens and cached_tokens

See dev/v2/MISTRAL_USAGE_PROBE.md for full probe results.
"""

from dataclasses import dataclass
from typing import Any, Literal


@dataclass
class CostBreakdown:
    """Breakdown of transcription cost.

    Attributes:
        audio_duration_seconds: Total audio duration used for billing.
        usage: Raw usage dict from Mistral response, or None if not available.
        estimated_cost_usd: Total estimated cost in USD.
        source: Where the cost calculation came from ('mistral_usage' or 'duration_fallback').
        token_cost_usd: Optional token-based portion of cost if calculated.
    """

    audio_duration_seconds: float
    usage: dict[str, Any] | None
    estimated_cost_usd: float
    source: Literal["mistral_usage", "duration_fallback"]
    token_cost_usd: float | None = None


def extract_usage(mistral_response: Any) -> dict[str, Any] | None:
    """Extract usage information from a Mistral transcription response.

    Attempts multiple access patterns to handle different SDK response shapes.
    Returns the usage dict if found, None otherwise.

    Args:
        mistral_response: The response object from Mistral's transcription API.

    Returns:
        The usage dict containing token and duration information, or None.

    Verified shape (mistralai==2.4.5, voxtral-mini-latest):
        {
            "prompt_tokens": int,
            "completion_tokens": int,
            "total_tokens": int,
            "prompt_audio_seconds": int,
            "prompt_tokens_details": {"audio_tokens": int, "cached_tokens": int},
        }
    """
    # Try direct .usage attribute
    if hasattr(mistral_response, "usage"):
        usage = getattr(mistral_response, "usage")
        if usage is not None:
            # If usage is a dict-like object, return it
            if hasattr(usage, "model_dump"):
                try:
                    return usage.model_dump()
                except Exception:
                    pass
            if isinstance(usage, dict):
                return usage

    # Try model_dump() which returns a dict with usage key
    if hasattr(mistral_response, "model_dump"):
        try:
            dumped = mistral_response.model_dump()
            if isinstance(dumped, dict) and "usage" in dumped:
                return dumped["usage"]
        except Exception:
            pass

    # Try __dict__ for plain objects
    if hasattr(mistral_response, "__dict__"):
        d = mistral_response.__dict__
        if isinstance(d, dict) and "usage" in d:
            return d["usage"]

    return None


def compute_cost(
    *,
    audio_duration_seconds: float,
    mistral_usage: dict[str, Any] | None,
    rate_usd_per_minute: float,
    input_token_rate_usd: float | None = None,
    output_token_rate_usd: float | None = None,
) -> CostBreakdown:
    """Compute transcription cost using Mistral usage or duration fallback.

    Billing priority:
    1. Duration-based billing using Mistral's prompt_audio_seconds (if available)
    2. Fallback to provided audio_duration_seconds

    Token-based billing (optional):
    - If input_token_rate_usd is configured, adds cost for prompt_tokens
    - If output_token_rate_usd is configured, adds cost for completion_tokens

    Args:
        audio_duration_seconds: Total audio duration for fallback calculation.
        mistral_usage: Raw usage dict from Mistral response, or None.
        rate_usd_per_minute: Rate for audio duration billing (USD per minute).
        input_token_rate_usd: Optional rate for input tokens (USD per token).
        output_token_rate_usd: Optional rate for output tokens (USD per token).

    Returns:
        CostBreakdown with computed costs and metadata.
    """
    duration_cost: float = 0.0
    token_cost: float = 0.0
    source: Literal["mistral_usage", "duration_fallback"] = "duration_fallback"
    usage_dict: dict[str, Any] | None = None

    if mistral_usage is not None:
        usage_dict = mistral_usage

        # Use Mistral's billed duration if available
        billed_seconds = mistral_usage.get("prompt_audio_seconds")
        if billed_seconds is not None:
            duration_cost = (float(billed_seconds) / 60.0) * rate_usd_per_minute
            source = "mistral_usage"
        else:
            # Fallback to provided duration
            duration_cost = (audio_duration_seconds / 60.0) * rate_usd_per_minute

        # Token-based billing (optional)
        if input_token_rate_usd is not None:
            prompt_tokens = mistral_usage.get("prompt_tokens", 0)
            token_cost += int(prompt_tokens) * input_token_rate_usd

        if output_token_rate_usd is not None:
            completion_tokens = mistral_usage.get("completion_tokens", 0)
            token_cost += int(completion_tokens) * output_token_rate_usd
    else:
        # Pure duration-based fallback
        duration_cost = (audio_duration_seconds / 60.0) * rate_usd_per_minute

    total_cost = duration_cost + token_cost

    return CostBreakdown(
        audio_duration_seconds=audio_duration_seconds,
        usage=usage_dict,
        estimated_cost_usd=total_cost,
        source=source,
        token_cost_usd=token_cost if token_cost > 0 else None,
    )
