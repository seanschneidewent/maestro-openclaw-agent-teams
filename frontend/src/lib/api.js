// api.js — Maestro API client
// Supports workspace URL shapes:
// 1) /<project-slug>/...
// 2) /agents/<agent-id>/workspace/...

function encodePathSegment(value) {
  return encodeURIComponent(value || '')
}

function getRouteContext() {
  const parts = window.location.pathname.split('/').filter(Boolean)
  if (parts[0] === 'agents' && parts[1] && parts[2] === 'workspace') {
    return {
      kind: 'agent',
      agentId: parts[1],
      projectSlug: '',
      prefix: `/agents/${encodePathSegment(parts[1])}/workspace`,
    }
  }
  return {
    kind: 'project',
    agentId: '',
    projectSlug: parts[0] || '',
    prefix: parts[0] ? `/${encodePathSegment(parts[0])}` : '',
  }
}

function getSlug() {
  return getRouteContext().projectSlug
}

const API_BASE = import.meta.env.VITE_API_URL || ''

function routePrefix() {
  return getRouteContext().prefix
}

async function request(path) {
  const res = await fetch(`${API_BASE}${routePrefix()}${path}`)
  if (!res.ok) {
    const error = await res.json().catch(() => ({ error: res.statusText }))
    throw new Error(error.error || `API error: ${res.status}`)
  }
  return res.json()
}

// Convenience exports
export const fetchPageRegions = (name) => request(`/api/pages/${encodeURIComponent(name)}/regions`)

export const getProjectSlug = getSlug

export const api = {
  // Project
  getProject: () => request('/api/project'),

  // Disciplines & Pages
  getDisciplines: () => request('/api/disciplines'),
  getPages: (discipline) => {
    const qs = discipline ? `?discipline=${encodeURIComponent(discipline)}` : ''
    return request(`/api/pages${qs}`)
  },
  getPage: (name) => request(`/api/pages/${encodeURIComponent(name)}`),

  // Images
  getPageImageUrl: (name) => `${API_BASE}${routePrefix()}/api/pages/${encodeURIComponent(name)}/image`,
  getPageThumbUrl: (name, w = 800, q = 80) =>
    `${API_BASE}${routePrefix()}/api/pages/${encodeURIComponent(name)}/thumb?w=${w}&q=${q}`,

  // Workspaces
  getWorkspaces: () => request('/api/workspaces'),
  getWorkspace: (slug) => request(`/api/workspaces/${encodeURIComponent(slug)}`),

  // Generated images
  getGeneratedImageUrl: (wsSlug, filename) =>
    `${API_BASE}${routePrefix()}/api/workspaces/${encodeURIComponent(wsSlug)}/images/${encodeURIComponent(filename)}`,
  getGeneratedImageThumbUrl: (wsSlug, filename, w = 800, q = 80) =>
    `${API_BASE}${routePrefix()}/api/workspaces/${encodeURIComponent(wsSlug)}/images/${encodeURIComponent(filename)}/thumb?w=${w}&q=${q}`,

  // Regions
  getRegions: (name) => request(`/api/pages/${encodeURIComponent(name)}/regions`),
  getRegion: (name, regionId) =>
    request(`/api/pages/${encodeURIComponent(name)}/regions/${encodeURIComponent(regionId)}`),
  getRegionCropUrl: (name, regionId) =>
    `${API_BASE}${routePrefix()}/api/pages/${encodeURIComponent(name)}/regions/${encodeURIComponent(regionId)}/crop`,

  // WebSocket URL
  getWsUrl: () => {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    return `${proto}//${host}${routePrefix()}/ws`
  },
}
