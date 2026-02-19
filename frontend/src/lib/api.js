// api.js — Maestro API client
// Reads project slug from URL path: /<slug>/...

// Extract slug from first path segment
function getSlug() {
  const parts = window.location.pathname.split('/').filter(Boolean)
  return parts[0] || ''
}

const API_BASE = import.meta.env.VITE_API_URL || ''

function slugPrefix() {
  const slug = getSlug()
  return slug ? `/${slug}` : ''
}

async function request(path) {
  const res = await fetch(`${API_BASE}${slugPrefix()}${path}`)
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
  getPageImageUrl: (name) => `${API_BASE}${slugPrefix()}/api/pages/${encodeURIComponent(name)}/image`,
  getPageThumbUrl: (name, w = 800, q = 80) =>
    `${API_BASE}${slugPrefix()}/api/pages/${encodeURIComponent(name)}/thumb?w=${w}&q=${q}`,

  // Workspaces
  getWorkspaces: () => request('/api/workspaces'),
  getWorkspace: (slug) => request(`/api/workspaces/${encodeURIComponent(slug)}`),

  // Generated images
  getGeneratedImageUrl: (wsSlug, filename) =>
    `${API_BASE}${slugPrefix()}/api/workspaces/${encodeURIComponent(wsSlug)}/images/${encodeURIComponent(filename)}`,
  getGeneratedImageThumbUrl: (wsSlug, filename, w = 800, q = 80) =>
    `${API_BASE}${slugPrefix()}/api/workspaces/${encodeURIComponent(wsSlug)}/images/${encodeURIComponent(filename)}/thumb?w=${w}&q=${q}`,

  // Regions
  getRegions: (name) => request(`/api/pages/${encodeURIComponent(name)}/regions`),
  getRegion: (name, regionId) =>
    request(`/api/pages/${encodeURIComponent(name)}/regions/${encodeURIComponent(regionId)}`),
  getRegionCropUrl: (name, regionId) =>
    `${API_BASE}${slugPrefix()}/api/pages/${encodeURIComponent(name)}/regions/${encodeURIComponent(regionId)}/crop`,

  // WebSocket URL
  getWsUrl: () => {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    return `${proto}//${host}${slugPrefix()}/ws`
  },
}
