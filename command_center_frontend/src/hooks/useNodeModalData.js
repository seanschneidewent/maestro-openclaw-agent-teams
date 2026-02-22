import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'

export default function useNodeModalData(project, control, awareness) {
  const [copied, setCopied] = useState(false)
  const [agentWorkspaces, setAgentWorkspaces] = useState([])
  const [workspacesLoading, setWorkspacesLoading] = useState(false)
  const [workspacesError, setWorkspacesError] = useState('')
  const [conversation, setConversation] = useState({ messages: [] })
  const [conversationLoading, setConversationLoading] = useState(false)
  const [conversationError, setConversationError] = useState('')
  const [statusPayload, setStatusPayload] = useState(null)
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)

  const isCommander = Boolean(project?.is_commander || project?.slug === 'commander')
  const preflightChecks = Array.isArray(control?.preflight?.checks) ? control.preflight.checks : []
  const workspaceBase =
    control?.workspace?.agent_workspace_url
    || control?.workspace?.project_workspace_url
    || (project?.slug && !isCommander ? `/${encodeURIComponent(project.slug)}/` : '')
  const canSend = !isCommander && Array.isArray(awareness?.available_actions)
    && awareness.available_actions.includes('conversation_send')

  useEffect(() => {
    let cancelled = false
    const agentId = control?.workspace?.agent_id
    const projectSlug = project?.slug
    if (isCommander || (!agentId && !projectSlug)) {
      setAgentWorkspaces([])
      setWorkspacesError('')
      setWorkspacesLoading(false)
      return () => {}
    }

    async function loadWorkspaces() {
      setWorkspacesLoading(true)
      setWorkspacesError('')
      try {
        let payload
        try {
          if (!agentId) throw new Error('missing_agent_route')
          payload = await api.getAgentWorkspaces(agentId)
        } catch (_agentRouteError) {
          if (!projectSlug) throw _agentRouteError
          payload = await api.getProjectWorkspaces(projectSlug)
        }
        if (cancelled) return
        const workspaces = Array.isArray(payload?.workspaces) ? payload.workspaces : []
        setAgentWorkspaces(workspaces)
      } catch (error) {
        if (!cancelled) {
          setAgentWorkspaces([])
          setWorkspacesError(error?.message || 'Failed to load workspaces')
        }
      } finally {
        if (!cancelled) {
          setWorkspacesLoading(false)
        }
      }
    }

    loadWorkspaces()
    return () => {
      cancelled = true
    }
  }, [control?.workspace?.agent_id, isCommander, project?.slug])

  useEffect(() => {
    let cancelled = false
    if (!project?.slug) return () => {}

    async function loadConversationAndStatus() {
      setConversationLoading(true)
      setConversationError('')
      try {
        const [conversationPayload, status] = await Promise.all([
          api.getNodeConversation(project.slug, { limit: 100 }),
          api.getNodeStatus(project.slug),
        ])
        if (cancelled) return
        setConversation(conversationPayload || { messages: [] })
        setStatusPayload(status || null)
      } catch (error) {
        if (!cancelled) {
          setConversation({ messages: [] })
          setStatusPayload(null)
          setConversationError(error?.message || 'Failed to load node conversation')
        }
      } finally {
        if (!cancelled) {
          setConversationLoading(false)
        }
      }
    }

    loadConversationAndStatus()
    const timer = window.setInterval(loadConversationAndStatus, 5000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [project?.slug])

  const copyCommand = async () => {
    const command = control?.ingest?.command
    if (!command) return
    try {
      await navigator.clipboard.writeText(command)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1200)
    } catch (error) {
      console.error('Failed to copy command', error)
    }
  }

  const sendMessage = async (messageOverride = '') => {
    if (!project?.slug) return
    const text = String(messageOverride || draft || '').trim()
    if (!text) return
    setSending(true)
    setConversationError('')
    try {
      const payload = await api.sendNodeMessage(project.slug, text, 'command_center_ui')
      if (payload?.conversation) {
        setConversation(payload.conversation)
      } else {
        const refreshed = await api.getNodeConversation(project.slug, { limit: 100 })
        setConversation(refreshed || { messages: [] })
      }
      const refreshedStatus = await api.getNodeStatus(project.slug)
      setStatusPayload(refreshedStatus || null)
      setDraft('')
    } catch (error) {
      setConversationError(error?.message || 'Failed to send message')
    } finally {
      setSending(false)
    }
  }

  return useMemo(
    () => ({
      copied,
      agentWorkspaces,
      workspacesLoading,
      workspacesError,
      conversation,
      conversationLoading,
      conversationError,
      statusPayload,
      draft,
      sending,
      isCommander,
      preflightChecks,
      workspaceBase,
      canSend,
      setDraft,
      copyCommand,
      sendMessage,
    }),
    [
      copied,
      agentWorkspaces,
      workspacesLoading,
      workspacesError,
      conversation,
      conversationLoading,
      conversationError,
      statusPayload,
      draft,
      sending,
      isCommander,
      preflightChecks,
      workspaceBase,
      canSend,
    ],
  )
}
