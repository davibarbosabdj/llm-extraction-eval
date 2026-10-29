"""Contrato comum a todos os extratores."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..schema import FIELDS


@dataclass
class ExtractionResult:
    doc_id: str
    extractor: str
    fields: dict = field(default_factory=lambda: {k: None for k in FIELDS})
    evidencia_resultado: str | None = None
    latency_s: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached: bool = False
    error: str | None = None
    raw: str | None = None

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "extractor": self.extractor,
            "fields": self.fields,
            "evidencia_resultado": self.evidencia_resultado,
            "latency_s": round(self.latency_s, 4),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cached": self.cached,
            "error": self.error,
            "raw": self.raw,
        }


class Extractor(Protocol):
    name: str

    def extract(self, doc_id: str, text: str) -> ExtractionResult: ...
