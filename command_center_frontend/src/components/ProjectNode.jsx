import React from 'react'

export default function ProjectNode({ project, onSelect }) {
  const nodeName = project.node_display_name || project.name
  const projectName = project.project_name || project.name
  const heartbeat = project.heartbeat || {}
  const convoPreview = project.conversation_preview || {}
  const statusReport = project.status_report || {}
  const loopState = String(statusReport.loop_state || heartbeat.loop_state || project.agent_status || 'idle').toLowerCase()
  const isFresh = !heartbeat.available || heartbeat.is_fresh
  const summary = statusReport.summary || convoPreview.last_assistant_text || project.current_task || 'Monitoring project telemetry'
  const assignee = project.assignee || project.superintendent || 'Unassigned'

  let chipClass = 'border-white/20 text-slate-300 bg-white/5'
  if (loopState === 'computing') chipClass = 'border-[#c084fc]/40 text-[#c084fc] bg-[#c084fc]/10'
  if (loopState === 'blocked') chipClass = 'border-amber-500/40 text-amber-400 bg-amber-500/10'
  if (!isFresh) chipClass = 'border-amber-500/40 text-amber-400 bg-amber-500/10'
  const chipLabel = !isFresh ? 'STALE' : loopState.toUpperCase()

  return (
    <button
      type="button"
      onClick={() => onSelect(project)}
      className="relative group w-full flex flex-col pt-6 cursor-pointer text-left"
      aria-label={`Open intelligence for ${nodeName}`}
    >
      <div className="absolute top-0 left-1/2 -ml-px w-px h-6 bg-gradient-to-b from-[#00e5ff]/40 to-white/10 group-hover:from-[#00e5ff] transition-colors duration-300" />
      <div className="absolute top-6 left-1/2 -ml-1 w-2 h-2 rounded-full bg-[#0a0e17] border border-[#00e5ff]/40 group-hover:border-[#00e5ff] group-hover:shadow-[0_0_8px_#00e5ff] transition-all z-10" />

      <div className="mt-2 bg-[#0a0e17] flex-grow border border-white/10 flex flex-col overflow-hidden transition-all duration-300 group-hover:border-[#00e5ff]/50 group-hover:-translate-y-1 group-hover:shadow-[0_10px_30px_-10px_rgba(0,229,255,0.15)]">
        <div className="h-1 w-full bg-white/10 group-hover:bg-[#00e5ff] transition-colors" />

        <div className="p-4 md:p-5 flex flex-col flex-grow">
          <div className="flex justify-between items-start mb-4 gap-2">
            <div>
              <h3 className="text-slate-200 font-medium tracking-wider uppercase text-sm">{nodeName}</h3>
              <div className="flex items-center gap-1.5 mt-1">
                <span className="text-slate-600 text-[10px] uppercase tracking-widest">PROJECT:</span>
                <span className="text-[#00e5ff] text-xs font-mono">{projectName}</span>
              </div>
              <div className="flex items-center gap-1.5 mt-1">
                <span className="text-slate-600 text-[10px] uppercase tracking-widest">ASSIGNEE:</span>
                <span className="text-[#00e5ff] text-xs font-mono">{assignee}</span>
              </div>
            </div>
            <div className={`px-2 py-1 border font-mono text-[10px] uppercase tracking-widest ${chipClass}`}>
              {chipLabel}
            </div>
          </div>

          <div className="flex-grow">
            <div className="text-[9px] text-slate-500 font-mono uppercase tracking-widest mb-1.5">
              Latest Update
            </div>
            <div className="text-xs text-slate-400 bg-black/40 p-2.5 border border-white/5 font-mono leading-relaxed min-h-14 flex items-center">
              <span className="text-[#00e5ff] mr-2">›</span>
              <span className="line-clamp-3">{summary}</span>
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-white/10 flex items-center justify-between text-[10px] font-mono uppercase tracking-widest">
            <span className="text-slate-500">{isFresh ? 'Heartbeat Fresh' : 'Heartbeat Stale'}</span>
            <span className="text-slate-400">{convoPreview.last_message_at || project.last_updated || '—'}</span>
          </div>
        </div>
      </div>
    </button>
  )
}
