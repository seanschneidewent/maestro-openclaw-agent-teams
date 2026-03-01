import React from 'react'

export default function AddNodeTile({ badge = '+', onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="relative group w-full flex flex-col pt-6 cursor-pointer text-left"
      aria-label="Add project maestro node"
    >
      <div className="absolute top-0 left-1/2 -ml-px w-px h-6 bg-gradient-to-b from-[#00e5ff]/30 to-white/10 group-hover:from-[#00e5ff] transition-colors duration-300" />
      <div className="absolute top-6 left-1/2 -ml-1 w-2 h-2 rounded-full bg-[#0a0e17] border border-[#00e5ff]/30 group-hover:border-[#00e5ff] group-hover:shadow-[0_0_8px_#00e5ff] transition-all z-10" />
      <div className="mt-2 bg-[#0a0e17] flex-grow border border-dashed border-white/20 group-hover:border-[#00e5ff]/50 transition-all duration-300 group-hover:-translate-y-1 group-hover:shadow-[0_10px_30px_-10px_rgba(0,229,255,0.15)] p-4 flex flex-col items-center justify-center min-h-[280px]">
        <div className="w-16 h-16 border border-[#00e5ff]/50 text-[#00e5ff] flex items-center justify-center font-mono text-2xl mb-4">
          {badge}
        </div>
        <div className="text-sm uppercase tracking-widest text-slate-300 text-center">Add Project Maestro</div>
        <div className="text-xs text-slate-500 text-center mt-2">Provision a new project agent + Telegram routing</div>
        <div className="text-[10px] text-slate-600 uppercase tracking-widest mt-4">Opens project create command</div>
      </div>
    </button>
  )
}
