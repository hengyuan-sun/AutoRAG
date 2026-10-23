import { describe, expect, it } from 'vitest'
import { sourceSegments } from './sourceView'

describe('source highlighting', () => {
  it('maps selected chunk character ranges back to source without changing text', () => {
    const parts = sourceSegments('规范😀温度为80℃', [{start: 2, end: 5}])
    expect(parts).toEqual([
      {text: '规范', marked: false},
      {text: '😀温度', marked: true},
      {text: '为80℃', marked: false},
    ])
    expect(parts.map(part => part.text).join('')).toBe('规范😀温度为80℃')
  })

  it('merges overlaps, clamps offsets, and ignores invalid ranges', () => {
    expect(sourceSegments('abcdef', [
      {start: -2, end: 2}, {start: 1, end: 4}, {start: 3, end: 9}, {start: 5, end: 5},
    ])).toEqual([{text: 'abcdef', marked: true}])
  })
})
