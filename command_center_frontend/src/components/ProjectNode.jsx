import React from 'react'

export default function ProjectNode({ project, onSelect }) {
  const variance = Number(project.health?.variance_days || 0)
  const isDelayed = variance < 0
  const isComputing = project.agent_status === 'computing'
  const blockers = Number(project.critical_path?.blocker_count || 0)
  const hasBlockers = blockers > 0

  return (
    <button
      type="button"
      onClick={() => onSelect(project)}
      className="relative group w-full flex flex-col pt-6 cursor-pointer text-left"
      aria-label={`Open intelligence for ${project.name}`}
    >
      <div className="absolute top-0 left-1/2 -ml-px w-px h-6 bg-gradient-to-b from-[#00e5ff]/40 to-white/10 group-hover:from-[#00e5ff] transition-colors duration-300" />
      <div className="absolute top-6 left-1/2 -ml-1 w-2 h-2 rounded-full bg-[#0a0e17] border border-[#00e5ff]/40 group-hover:border-[#00e5ff] group-hover:shadow-[0_0_8px_#00e5ff] transition-all z-10" />

      <div
        className={`mt-2 bg-[#0a0e17] flex-grow border flex flex-col overflow-hidden transition-all duration-300 ${
          hasBlockers ? 'border-amber-500/30' : 'border-white/10'
        } group-hover:border-[#00e5ff]/50 group-hover:-translate-y-1 group-hover:shadow-[0_10px_30px_-10px_rgba(0,229,255,0.15)]`}
      >
        <div className={`h-1 w-full ${isDelayed ? 'bg-amber-500/50' : 'bg-white/10'} group-hover:bg-[#00e5ff] transition-colors`} />

        <div className="p-4 md:p-5 flex flex-col flex-grow">
          <div className="flex justify-between items-start mb-4 gap-2">
            <div>
              <h3 className="text-slate-200 font-medium tracking-wider uppercase text-sm">{project.name}</h3>
              <div className="flex items-center gap-1.5 mt-1">
                <span className="text-slate-600 text-[10px] uppercase tracking-widest">ASSIGNEE:</span>
                <span className="text-[#00e5ff] text-xs font-mono">{project.assignee || project.superintendent || 'Unassigned'}</span>
              </div>
            </div>
            <div
              className={`px-2 py-1 border font-mono text-[10px] uppercase tracking-widest ${
                isDelayed ? 'border-amber-500/30 text-amber-500 bg-amber-500/10' : 'border-[#00e676]/30 text-[#00e676] bg-[#00e676]/10'
              }`}
            >
              {variance >= 0 ? `+${variance}D` : `${variance}D`}
            </div>
          </div>

          <div className="mb-5 flex-grow">
            <div className="text-[9px] text-slate-500 font-mono uppercase tracking-widest mb-1.5 flex justify-between items-center">
              <span>Current Loop</span>
              {isComputing && (
                <span className="text-[#c084fc] flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#c084fc] animate-pulse" /> Computing
                </span>
              )}
            </div>
            <div className="text-xs text-slate-400 bg-black/40 p-2.5 border border-white/5 font-mono leading-relaxed h-14 flex items-center">
              <span className="text-[#00e5ff] mr-2">›</span>
              <span className="line-clamp-2">{project.current_task || 'Monitoring project telemetry'}</span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-px bg-white/5 mt-auto">
            <div className="bg-[#0a0e17] p-2 flex flex-col items-center">
              <span className="text-[9px] text-slate-600 font-mono uppercase tracking-widest mb-1">Blockers</span>
              <span className={`font-mono text-lg ${hasBlockers ? 'text-amber-500 shadow-amber-500/20 drop-shadow-md' : 'text-slate-400'}`}>
                {blockers}
              </span>
            </div>
            <div className="bg-[#0a0e17] p-2 flex flex-col items-center">
              <span className="text-[9px] text-slate-600 font-mono uppercase tracking-widest mb-1">Open RFIs</span>
              <span className="font-mono text-lg text-slate-400">{project.rfis?.open || 0}</span>
            </div>
          </div>
        </div>

        <div className="absolute top-4 right-0 translate-x-2 opacity-0 group-hover:-translate-x-2 group-hover:opacity-100 transition-all duration-300 z-20 pointer-events-none">
          <div className="bg-[#00e5ff] text-black px-3 py-1.5 flex items-center gap-2 shadow-[0_0_15px_rgba(0,229,255,0.4)]">
            <span className="font-mono text-[9px] uppercase tracking-widest font-bold">{project.comms || `Attention ${project.attention_score || 0}`}</span>
          </div>
        </div>
      </div>
    </button>
  )
}
