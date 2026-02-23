import React from 'react'
import { DrawerCard } from './shared'

export default function WorkspaceAccessSection({
  isCommander,
  workspaceBase,
  workspacesLoading,
  workspacesError,
  agentWorkspaces,
}) {
  if (isCommander) {
    return (
      <DrawerCard title="Workspace Access">
        <div className="text-xs text-slate-400">
          Commander node does not have a project workspace frontend.
        </div>
      </DrawerCard>
    )
  }

  return (
    <DrawerCard title="Workspace Access">
      <div className="space-y-2 text-xs">
        <div className="bg-black/40 border border-white/10 p-2">
          <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Project Workspace</div>
          <a
            href={workspaceBase || '#'}
            className="font-mono text-slate-100 break-all underline decoration-slate-500/40 hover:text-[#00e5ff]"
          >
            {workspaceBase || 'Unavailable'}
          </a>
        </div>
        <div className="bg-black/40 border border-white/10 p-2">
          <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Agent Workspaces</div>
          {workspacesLoading ? (
            <div className="text-[11px] text-slate-400">Loading workspaces...</div>
          ) : workspacesError ? (
            <div className="text-[11px] text-amber-400">{workspacesError}</div>
          ) : agentWorkspaces.length === 0 ? (
            <div className="text-[11px] text-slate-500">No workspaces yet for this agent.</div>
          ) : (
            <div className="space-y-1.5">
              {agentWorkspaces.map((ws) => {
                const wsSlug = ws?.slug || ''
                const wsName = ws?.title || wsSlug || 'Workspace'
                const href = workspaceBase
                  ? `${workspaceBase}?workspace=${encodeURIComponent(wsSlug)}`
                  : '#'
                return (
                  <a
                    key={wsSlug || wsName}
                    href={href}
                    className="block text-[11px] font-mono text-slate-200 underline decoration-slate-500/40 hover:text-[#00e5ff]"
                  >
                    {wsName}
                  </a>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </DrawerCard>
  )
}

