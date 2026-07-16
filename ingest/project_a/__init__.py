"""Deterministic Project A ingest, state, and durable outbox runtime."""

from .config import ProjectAConfig
from .service import IngestResult, ProjectAIngestService

__all__ = ["IngestResult", "ProjectAConfig", "ProjectAIngestService"]
