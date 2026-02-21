import React from 'react'

function SignalPulse() {
  return (
    <span className="relative flex h-2 w-2">
      <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 bg-[#00e5ff]" />
      <span className="relative inline-flex rounded-full h-2 w-2 bg-[#00e5ff]" />
    </span>
  )
}

export default function DirectiveLog({ directive }) {
  const isActive = directive.status === 'broadcasting'

  return (
    <div
      className={`relative overflow-hidden p-4 border transition-all duration-500 ${
        isActive
          ? 'border-[#00e5ff]/50 bg-[#00e5ff]/5 shadow-[0_0_15px_rgba(0,229,255,0.1)]'
          : 'border-white/5 bg-white/[0.02]'
      }`}
    >
      {isActive && <div className="absolute top-0 left-0 w-1 h-full bg-[#00e5ff] animate-pulse" />}

      <div className="flex justify-between items-center mb-3">
        <div className="flex items-center gap-2">
          {isActive && <SignalPulse />}
          <span className={`font-mono text-[10px] tracking-widest uppercase ${isActive ? 'text-[#00e5ff]' : 'text-slate-500'}`}>
            {directive.id || 'DIR-000'} // {directive.status || 'info'}
          </span>
        </div>
        <span className="font-mono text-[10px] text-slate-500">{directive.timestamp || '—'}</span>
      </div>

      <div className="mb-4">
        <span className="text-[9px] uppercase tracking-widest text-slate-500 block mb-1">
          Source: {directive.source || 'Command Center'}
        </span>
        <p className="text-slate-300 text-sm leading-relaxed font-sans border-l border-slate-700 pl-3">
          "{directive.command || 'No directives yet. Company Maestro is monitoring project telemetry.'}"
        </p>
      </div>

      <div className="bg-black/40 p-2 border border-white/5 flex items-center justify-between">
        <span className="text-[9px] uppercase tracking-widest text-slate-500">Fleet Response</span>
        <span className={`text-[10px] font-mono ${isActive ? 'text-amber-400' : 'text-[#00e676]'}`}>
          {directive.acknowledgments || 'Monitoring'}
        </span>
      </div>
    </div>
  )
}
