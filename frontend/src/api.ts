export async function api(path: string, token: string, options: RequestInit = {}): Promise<any> {
  const headers: Record<string, string> = { Authorization: `Bearer ${token}`, ...(options.headers as Record<string, string> || {}) }
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json'
  const response = await fetch(`/api/v1${path}`, { ...options, headers })
  const data = await response.json()
  if (!response.ok) {
    const detail = data.message || (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail))
    throw new Error(detail || `请求失败 ${response.status}`)
  }
  return data
}
