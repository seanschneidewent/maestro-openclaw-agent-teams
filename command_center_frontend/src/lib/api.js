async function getJson(url) {
  const response = await fetch(url)
  if (!response.ok) {
    const body = await response.text()
    throw new Error(`HTTP ${response.status}: ${body}`)
  }
  return response.json()
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  })
  if (!response.ok) {
    const body = await response.text()
    throw new Error(`HTTP ${response.status}: ${body}`)
  }
  return response.json()
}

export const api = {
  getState: () => getJson('/api/command-center/state'),
  getProjectDetail: (slug) => getJson(`/api/command-center/projects/${encodeURIComponent(slug)}`),
  getAwareness: () => getJson('/api/system/awareness'),
  runAction: (action, payload = {}) => postJson('/api/command-center/actions', { action, ...payload }),
}
