export type CharacterRange = { start: number; end: number }
export type SourceSegment = { text: string; marked: boolean }

/** Python stores offsets as Unicode code points; Array.from preserves the same unit in JavaScript. */
export function sourceSegments(text: string, ranges: CharacterRange[]): SourceSegment[] {
  const chars = Array.from(text)
  const normalized = ranges
    .filter(range => Number.isInteger(range.start) && Number.isInteger(range.end) && range.start < range.end)
    .map(range => ({start: Math.max(0, Math.min(chars.length, range.start)),
      end: Math.max(0, Math.min(chars.length, range.end))}))
    .filter(range => range.start < range.end)
    .sort((a, b) => a.start - b.start || a.end - b.end)
  const merged: CharacterRange[] = []
  for (const range of normalized) {
    const previous = merged.at(-1)
    if (previous && range.start <= previous.end) previous.end = Math.max(previous.end, range.end)
    else merged.push({...range})
  }
  const parts: SourceSegment[] = []
  let cursor = 0
  for (const range of merged) {
    if (range.start > cursor) parts.push({text: chars.slice(cursor, range.start).join(''), marked: false})
    parts.push({text: chars.slice(range.start, range.end).join(''), marked: true})
    cursor = range.end
  }
  if (cursor < chars.length) parts.push({text: chars.slice(cursor).join(''), marked: false})
  return parts.length ? parts : [{text, marked: false}]
}
