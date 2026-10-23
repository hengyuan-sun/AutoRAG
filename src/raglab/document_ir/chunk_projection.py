"""Project selected canonical IR items into the existing chunker input format."""

from collections import defaultdict

from .models import DocumentIR, TableItem


def to_chunking_document(ir: DocumentIR, document_id: str) -> dict:
    """Keep IR intact while producing text blocks with exact item and cell offsets."""
    blocks = []
    heading_stack: list[tuple[int, str]] = []
    ordered = sorted(enumerate(ir.items), key=lambda pair: (
        pair[1].order if pair[1].order is not None else pair[0], pair[0]))

    for fallback_order, item in ordered:
        if item.type not in {"heading", "paragraph", "table"}:
            continue
        if item.type == "heading":
            level = max(1, getattr(item, "level", 1))
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, item.text))
            section_path = item.chapter_path or [text for _, text in heading_stack]
        else:
            section_path = item.chapter_path or [text for _, text in heading_stack]

        text, rows, cell_spans = _table_text(item) if isinstance(item, TableItem) else (item.text, None, [])
        if not text.strip():
            continue
        locations = [location.model_dump(mode="json", exclude_none=True)
                     for location in item.provenance.locations]
        primary = item.provenance.locations[0] if item.provenance.locations else None
        page = item.provenance.page or (primary.page if primary else None)
        bbox = item.provenance.bbox or (primary.bbox if primary else None)
        blocks.append({
            "id": item.uid,
            "item_uid": item.uid,
            "item_type": item.type,
            "type": "table" if item.type == "table" else "text",
            "text": text,
            "section_path": section_path,
            "page": page,
            "bbox": list(bbox) if bbox is not None else None,
            "locations": locations,
            "rows": rows,
            "cell_spans": cell_spans,
            "source": item.provenance.source,
            "source_spans": [span.model_dump(mode="json", exclude_none=True)
                             for span in item.provenance.source_spans],
            "order": item.order if item.order is not None else fallback_order,
        })
    return {"revision": document_id, "blocks": blocks}


def _table_text(item: TableItem):
    if not item.cells:
        value = item.table_markdown or "\n".join(item.linearized_rows)
        rows = value.splitlines()
        return value, rows, []

    cells_by_row = defaultdict(list)
    for cell in item.cells:
        cells_by_row[cell.row].append(cell)
    row_texts, cell_spans = [], []
    cursor = 0
    for row_number in sorted(cells_by_row):
        parts, row_position = [], 0
        for cell in sorted(cells_by_row[row_number], key=lambda value: (value.col, value.uid or "")):
            if parts:
                parts.append(" | ")
                row_position += 3
            cell_text = cell.text
            start = cursor + row_position
            row_position += len(cell_text)
            parts.append(cell_text)
            cell_spans.append({"item_uid": item.uid, "cell_uid": cell.uid,
                               "row": cell.row, "col": cell.col,
                               "start": start, "end": cursor + row_position})
        row = "".join(parts)
        row_texts.append(row)
        cursor += len(row) + 1
    text = "\n".join(row_texts)
    return text, row_texts, cell_spans
