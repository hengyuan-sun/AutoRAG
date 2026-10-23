"""Canonical, versioned document intermediate representation."""

from .models import DocumentIR, EvidenceStatus, ItemKind
from .validation import validate_document_ir

__all__ = ["DocumentIR", "EvidenceStatus", "ItemKind", "validate_document_ir"]
