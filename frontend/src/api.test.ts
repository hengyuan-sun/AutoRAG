import { expect, test, vi } from 'vitest'
import { api } from './api'

test('请求携带访问令牌并显示结构化错误', async () => {
  const fetcher = vi.fn().mockResolvedValue({ok: false, json: async () => ({message: '版本冲突'})})
  vi.stubGlobal('fetch', fetcher)
  await expect(api('/releases', 'secret')).rejects.toThrow('版本冲突')
  expect(fetcher.mock.calls[0][1].headers.Authorization).toBe('Bearer secret')
})
