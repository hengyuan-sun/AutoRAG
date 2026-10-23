"""Cross-reference and table invariants for DocumentIR."""

import math

from .models import DocumentIR


def validate_document_ir(ir: DocumentIR) -> DocumentIR:
    items = [*ir.items, *ir.toc, *ir.header_footer]
    by_uid = {}
    for item in items:
        if item.uid in by_uid:
            raise ValueError(f"item {item.uid}: duplicate uid")
        by_uid[item.uid] = item

    for item in items:
        if item.parent_uid and item.parent_uid not in by_uid:
            raise ValueError(f"item {item.uid}: unknown parent_uid {item.parent_uid}")
        if getattr(item, "type", None) == "table":
            for cell in item.cells:
                if (item.n_rows and cell.row >= item.n_rows) or (item.n_cols and cell.col >= item.n_cols):
                    raise ValueError(f"item {item.uid}: cell {cell.uid or (cell.row, cell.col)} outside table bounds")
        for span in item.provenance.source_spans:
            if span.end < span.start:
                raise ValueError(f"item {item.uid}: invalid source span")
        for location in item.provenance.locations:
            if location.bbox and any(not math.isfinite(value) for value in location.bbox):
                raise ValueError(f"item {item.uid}: nonfinite location bbox")

    for relation in ir.relations:
        if relation.source_uid not in by_uid:
            raise ValueError(f"relation source {relation.source_uid}: unknown uid")
        if relation.target_uid not in by_uid:
            raise ValueError(f"relation target {relation.target_uid}: unknown uid")
    for node in _outline_nodes(ir.outline):
        for uid in node.item_uids:
            if uid not in by_uid:
                raise ValueError(f"outline {node.title}: unknown item uid {uid}")
    return ir


def _outline_nodes(nodes):
    for node in nodes:
        yield node
        yield from _outline_nodes(node.children)
