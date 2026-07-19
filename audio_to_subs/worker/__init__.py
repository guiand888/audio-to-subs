"""Worker module for background job processing.

The worker runs as a separate process, claiming jobs from the queue and
executing them through the pipeline. Progress updates are published via Redis
and stored in the database.
"""

from audio_to_subs.worker.progress import ProgressBridge
from audio_to_subs.worker.runner import WorkerDeps, run_job

__all__ = [
    "ProgressBridge",
    "run_job",
    "WorkerDeps",
]
