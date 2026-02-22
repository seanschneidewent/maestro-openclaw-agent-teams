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
  getNodeStatus: (slug) => getJson(`/api/command-center/nodes/${encodeURIComponent(slug)}/status`),
  getNodeConversation: (slug, { limit = 100, before = '' } = {}) => {
    const params = new URLSearchParams()
    params.set('limit', String(limit))
    if (before) params.set('before', before)
    return getJson(`/api/command-center/nodes/${encodeURIComponent(slug)}/conversation?${params.toString()}`)
  },
  sendNodeMessage: (slug, message, source = 'command_center_ui') =>
    postJson(`/api/command-center/nodes/${encodeURIComponent(slug)}/conversation/send`, { message, source }),
  getAwareness: () => getJson('/api/system/awareness'),
  getAgentWorkspaces: (agentId) => getJson(`/agents/${encodeURIComponent(agentId)}/workspace/api/workspaces`),
  getProjectWorkspaces: (projectSlug) => getJson(`/${encodeURIComponent(projectSlug)}/api/workspaces`),
  runAction: (action, payload = {}) => postJson('/api/command-center/actions', { action, ...payload }),
  listSystemDirectives: (includeArchived = false) =>
    postJson('/api/command-center/actions', {
      action: 'list_system_directives',
      include_archived: includeArchived,
    }),
  upsertSystemDirective: (directive, updatedBy = 'command_center_ui') =>
    postJson('/api/command-center/actions', {
      action: 'upsert_system_directive',
      directive,
      updated_by: updatedBy,
    }),
  archiveSystemDirective: (directiveId, updatedBy = 'command_center_ui') =>
    postJson('/api/command-center/actions', {
      action: 'archive_system_directive',
      directive_id: directiveId,
      updated_by: updatedBy,
    }),
}
