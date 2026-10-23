import { describe, expect, test } from 'vitest'
import { fieldPreviewRows, isSupportedSelector, locationLabel } from './consumerProfiles'

describe('Consumer Profile UI helpers', () => {
  test('accepts only the documented selector grammar', () => {
    expect(isSupportedSelector('meta.filename')).toBe(true)
    expect(isSupportedSelector('items[*].provenance.page')).toBe(true)
    expect(isSupportedSelector('items[*].cells[*].text')).toBe(true)
    expect(isSupportedSelector('items[*].__class__')).toBe(false)
    expect(isSupportedSelector('items[*].text | eval()')).toBe(false)
  })

  test('formats preview values with source identity and source location', () => {
    const rows = fieldPreviewRows({values: [
      {value: '压力12MPa', source_uid: 'ir_p2', location: {page: 4, bbox: [1, 2, 3, 4]}},
      {value: '未定位', source_uid: 'ir_p3', location: null},
    ]})
    expect(rows.map(row => row.source_uid)).toEqual(['ir_p2', 'ir_p3'])
    expect(rows[0].locationText).toContain('第4页')
    expect(rows[0].locationText).toContain('bbox')
    expect(rows[1].locationText).toBe('未提供定位')
    expect(locationLabel({source_spans: [{start: 2, end: 8}]})).toContain('[2,8)')
  })
})
