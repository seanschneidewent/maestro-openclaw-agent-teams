import { useCallback, useState } from 'react'
import { api } from '../lib/api'

async function fetchProjectPayloads(slug) {
  if (slug === 'commander') {
    return {
      detailResult: { status: 'fulfilled', value: { snapshot: { slug: 'commander' }, drawers: {} } },
      controlResult: { status: 'fulfilled', value: null },
    }
  }
  const [detailResult, controlResult] = await Promise.allSettled([
    api.getProjectDetail(slug),
    api.runAction('ingest_command', { project_slug: slug }),
  ])
  return { detailResult, controlResult }
}

export default function useProjectModalData() {
  const [selectedProject, setSelectedProject] = useState(null)
  const [selectedDetail, setSelectedDetail] = useState(null)
  const [selectedControl, setSelectedControl] = useState(null)
  const [loadingDetail, setLoadingDetail] = useState(false)

  const clearSelection = useCallback(() => {
    setSelectedProject(null)
    setSelectedDetail(null)
    setSelectedControl(null)
  }, [])

  const selectProject = useCallback(async (project) => {
    if (!project?.slug) return
    setSelectedProject(project)
    setSelectedDetail(null)
    setSelectedControl(null)
    if (project.slug === 'commander') {
      setLoadingDetail(false)
      return
    }
    setLoadingDetail(true)

    const { detailResult, controlResult } = await fetchProjectPayloads(project.slug)

    if (detailResult.status === 'fulfilled') {
      setSelectedDetail(detailResult.value)
    } else {
      console.error('Failed to load project detail', detailResult.reason)
      setSelectedDetail({ snapshot: project, drawers: {} })
    }

    if (controlResult.status === 'fulfilled') {
      setSelectedControl(controlResult.value)
    } else {
      console.error('Failed to load project control payload', controlResult.reason)
      setSelectedControl(null)
    }

    setLoadingDetail(false)
  }, [])

  const refreshSelectedProject = useCallback(async (projectSlug = null) => {
    const slug = projectSlug || selectedProject?.slug
    if (!slug) return
    if (slug === 'commander') return

    const { detailResult, controlResult } = await fetchProjectPayloads(slug)
    if (detailResult.status === 'fulfilled') {
      setSelectedDetail(detailResult.value)
    }
    if (controlResult.status === 'fulfilled') {
      setSelectedControl(controlResult.value)
    }
  }, [selectedProject?.slug])

  const syncSelectedProjectFromState = useCallback((projects = []) => {
    if (!selectedProject?.slug || !Array.isArray(projects)) return
    const latest = projects.find((project) => project?.slug === selectedProject.slug)
    if (latest) setSelectedProject(latest)
  }, [selectedProject?.slug])

  return {
    selectedProject,
    selectedDetail,
    selectedControl,
    loadingDetail,
    selectProject,
    refreshSelectedProject,
    clearSelection,
    syncSelectedProjectFromState,
  }
}
