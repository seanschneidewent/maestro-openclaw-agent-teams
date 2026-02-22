import React from 'react'
import StatusSummaryCard from './StatusSummaryCard'
import { DrawerCard } from './shared'

export default function ControlPlaneSection({
  awareness,
  statusPayload,
  isCommander,
  workspaceBase,
  workspacesLoading,
  workspacesError,
  agentWorkspaces,
  control,
  preflightChecks,
  copied,
  onCopyCommand,
}) {
  return (
    <DrawerCard title="Control Plane" className="xl:col-span-2">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
        <div className="space-y-2">
          <div className="bg-black/40 border border-white/10 p-2">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">Recommended URL</div>
            <div className="font-mono text-slate-100 break-all">{awareness?.network?.recommended_url || 'Unknown'}</div>
          </div>
          <div className="bg-black/40 border border-white/10 p-2">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">Knowledge Store Root</div>
            <div className="font-mono text-slate-100 break-all">{awareness?.paths?.store_root || 'Unknown'}</div>
          </div>
          <div className="bg-black/40 border border-white/10 p-2">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">System Posture</div>
            <div className={`font-mono ${awareness?.posture === 'healthy' ? 'text-[#00e676]' : 'text-amber-400'}`}>
              {(awareness?.posture || 'Unknown').toUpperCase()}
            </div>
          </div>
          <StatusSummaryCard status={statusPayload} />
        </div>
        <div className="space-y-2">
          {!isCommander && (
            <>
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
                <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Workspaces</div>
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
              <div className="bg-black/40 border border-white/10 p-2">
                <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Ingest Command</div>
                <code className="block text-[11px] leading-relaxed text-slate-200 break-words">{control?.ingest?.command || 'Unavailable'}</code>
                <div className="mt-2 flex items-center gap-2">
                  <button
                    type="button"
                    onClick={onCopyCommand}
                    className="border border-white/20 text-slate-300 px-2 py-1 text-[10px] uppercase tracking-widest font-mono hover:border-[#00e5ff] hover:text-[#00e5ff]"
                  >
                    {copied ? 'Copied' : 'Copy'}
                  </button>
                  {control?.ingest?.needs_input_path && (
                    <span className="text-amber-400 text-[10px] uppercase tracking-widest">Set input path first</span>
                  )}
                </div>
              </div>
              <div className="bg-black/40 border border-white/10 p-2">
                <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Preflight</div>
                {preflightChecks.length === 0 ? (
                  <span className="text-slate-500">No preflight data.</span>
                ) : (
                  <div className="space-y-1">
                    {preflightChecks.map((check) => (
                      <div key={check.name} className="flex justify-between gap-3">
                        <span className="text-slate-300">{check.name}</span>
                        <span className={check.ok ? 'text-[#00e676] font-mono' : 'text-amber-400 font-mono'}>
                          {check.ok ? 'ok' : 'missing'}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
          {isCommander && (
            <div className="bg-black/40 border border-white/10 p-2">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">Commander Agent</div>
              <div className="font-mono text-slate-200 mt-1">{awareness?.commander?.agent_id || 'maestro-company'}</div>
              <div className="text-[11px] text-slate-400 mt-2">
                Commander modal is conversation-first and control-plane only.
              </div>
            </div>
          )}
        </div>
      </div>
    </DrawerCard>
  )
}

