"""Model specifications for Mistral transcription models."""

MODEL_SPECS: dict[str, dict[str, int | str]] = {
    "voxtral-mini-2602": {
        "max_audio_length": 10800,
        "label": "Voxtral Mini Transcribe 2",
    },
    "voxtral-mini-latest": {
        "max_audio_length": 10800,
        "label": "Voxtral Mini (latest)",
    },
    "voxtral-mini-2507": {"max_audio_length": 900, "label": "Voxtral Mini Transcribe"},
    "voxtral-small-2507": {"max_audio_length": 900, "label": "Voxtral Small 2507"},
}

DEFAULT_MAX_AUDIO_LENGTH = 900
MAX_AUDIO_LENGTH_BOUNDS = (60, 10800)
