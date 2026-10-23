export type ProfileFieldValue = {
  value: unknown
  source_uid: string | null
  location: Record<string, unknown> | null
}

export type ProfileFieldPreview = {
  selector: string
  aliases?: string[]
  status: string
  values: ProfileFieldValue[]
  required?: boolean
}

export type ProfilePreviewRow = ProfileFieldValue & { locationText: string }

const scalarFields = new Set(['uid', 'text', 'chapter_path', 'parent_uid', 'order', 'status', 'status_reason',
  'evidence_refs', 'extensions', 'level', 'number', 'format', 'image_uids', 'title', 'grid_complete',
  'grid_status_reason', 'n_rows', 'n_cols', 'has_header', 'table_markdown', 'table_json', 'linearized_rows',
  'image_refs', 'caption_paragraph_uid', 'filename', 'pic_summary', 'llm_description', 'width_px', 'height_px',
  'media_artifact', 'source_relationship_id', 'source_container_uid', 'latex', 'source_image', 'target_number',
  'kind', 'page'])
const metadataFields = new Set(['doc_id', 'filename', 'sha256', 'size_bytes', 'detected_format', 'original_format',
  'conversion_applied', 'encryption_state'])
const provenanceFields = new Set(['item_id', 'xpath', 'page', 'bbox', 'source', 'source_spans', 'locations'])
const cellFields = new Set(['uid', 'text', 'row', 'col', 'rowspan', 'colspan', 'is_header', 'provenance',
  'source_spans', 'content_uids', 'status', 'status_reason', 'evidence_refs'])
const outlineFields = new Set(['title', 'level', 'number', 'item_uids'])

export function isSupportedSelector(selector: string): boolean {
  const parts = selector.split('.')
  if (parts.length === 2 && parts[0] === 'meta') return metadataFields.has(parts[1])
  if (parts.length === 2 && parts[0] === 'outline[*]') return outlineFields.has(parts[1])
  if (parts.length === 2 && parts[0] === 'items[*]') return scalarFields.has(parts[1])
  if (parts.length === 3 && parts[0] === 'items[*]' && parts[1] === 'provenance') return provenanceFields.has(parts[2])
  if (parts.length === 3 && parts[0] === 'items[*]' && parts[1] === 'cells[*]') return cellFields.has(parts[2])
  return false
}

export function locationLabel(location: Record<string, unknown> | null | undefined): string {
  if (!location) return '未提供定位'
  const labels: string[] = []
  if (typeof location.page === 'number') labels.push(`第${location.page}页`)
  if (Array.isArray(location.bbox)) labels.push(`bbox ${JSON.stringify(location.bbox)}`)
  if (Array.isArray(location.source_spans)) {
    labels.push(...location.source_spans.map((span: any) => `[${span.start},${span.end})`))
  }
  if (Array.isArray(location.locations)) {
    labels.push(...location.locations.map((child: any) => locationLabel(child)).filter((text: string) => text !== '未提供定位'))
  }
  return labels.length ? [...new Set(labels)].join(' · ') : '未提供定位'
}

export function fieldPreviewRows(field: Pick<ProfileFieldPreview, 'values'>): ProfilePreviewRow[] {
  return (field.values || []).map(value => ({...value, locationText: locationLabel(value.location)}))
}
