import React, { useEffect, useRef } from 'react'
import useNodeModalData from '../hooks/useNodeModalData'
import ControlPlaneSection from './node_modal/ControlPlaneSection'
import ConversationSection from './node_modal/ConversationSection'
import ScheduleSection from './node_modal/ScheduleSection'
import WorkspaceAccessSection from './node_modal/WorkspaceAccessSection'

export default function NodeIntelligenceModal({ project, detail, awareness, control, onClose }) {
  const panelRef = useRef(null)
  const {
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
    workspaceBase,
    canSend,
    setDraft,
    sendMessage,
  } = useNodeModalData(project, control, awareness)

  useEffect(() => {
    const panel = panelRef.current
    if (!panel) return undefined

    const focusable = panel.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    )
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (first) first.focus()

    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key === 'Tab' && focusable.length > 1) {
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault()
          last.focus()
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault()
          first.focus()
        }
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
      role="presentation"
    >
      <div
        ref={panelRef}
        className="w-full h-full md:h-auto md:max-h-[90vh] md:max-w-6xl overflow-auto bg-[#05080f] border border-[#00e5ff]/30 p-5 md:p-6"
        role="dialog"
        aria-modal="true"
        aria-label={`Node Intelligence - ${project.node_display_name || project.name || 'Node'}`}
      >
        <div className="flex justify-between items-start mb-5 gap-4">
          <div>
            <p className="text-[10px] uppercase tracking-widest font-mono text-slate-500">Node Intelligence Drawer</p>
            <h2 className="text-xl md:text-2xl text-white uppercase tracking-widest mt-1">{project.node_display_name || project.name}</h2>
            <p className="text-xs text-slate-400 mt-1">
              Project <span className="text-[#00e5ff] font-mono">{project.project_name || project.name || 'Control Plane'}</span>
              {' · '}
              Last Updated <span className="text-slate-300 font-mono">{project.last_updated || '—'}</span>
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="border border-white/20 text-slate-300 px-3 py-1.5 text-xs uppercase tracking-widest font-mono hover:border-[#00e5ff] hover:text-[#00e5ff]"
          >
            Close
          </button>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <ControlPlaneSection
            awareness={awareness}
            statusPayload={statusPayload}
            isCommander={isCommander}
          />

          <WorkspaceAccessSection
            isCommander={isCommander}
            workspaceBase={workspaceBase}
            workspacesLoading={workspacesLoading}
            workspacesError={workspacesError}
            agentWorkspaces={agentWorkspaces}
          />

          <ConversationSection
            loading={conversationLoading}
            error={conversationError}
            conversation={conversation}
            sendEnabled={canSend}
            sending={sending}
            draft={draft}
            setDraft={setDraft}
            onSend={sendMessage}
          />

          <ScheduleSection
            isCommander={isCommander}
            detail={detail}
            statusPayload={statusPayload}
          />
        </div>
      </div>
    </div>
  )
}
