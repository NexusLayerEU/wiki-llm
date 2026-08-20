"""Shared column helpers."""
import uuid
from datetime import datetime, timezone


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """Timezone-aware UTC. Naive datetimes compare unpredictably once any part of
    the stack starts attaching a tzinfo, which SQLite will not warn about."""
    return datetime.now(timezone.utc)
