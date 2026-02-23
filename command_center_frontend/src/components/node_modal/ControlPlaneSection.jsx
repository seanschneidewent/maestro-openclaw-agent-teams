import React from 'react'
import { DrawerCard } from './shared'

export default function ControlPlaneSection({
  awareness,
  statusPayload,
  isCommander,
}) {
  const report = statusPayload?.status_report || {}
  const posture = String(awareness?.posture || 'unknown').toUpperCase()
  const loopState = String(report.loop_state || 'idle').toUpperCase()
  const source = String(report.source || 'computed').toUpperCase()

  return (
    <DrawerCard title="Control Plane">
      <div className="space-y-2 text-xs">
        <div className="bg-black/40 border border-white/10 p-2">
          <div className="text-[10px] uppercase tracking-widest text-slate-500">Summary</div>
          <div className="text-slate-200 mt-1">{report.summary || 'No control-plane summary yet.'}</div>
        </div>
        <div className="grid grid-cols-3 gap-2">
          <div className="bg-black/40 border border-white/10 p-2">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">Posture</div>
            <div className={`font-mono mt-1 ${awareness?.posture === 'healthy' ? 'text-[#00e676]' : 'text-amber-400'}`}>
              {posture}
            </div>
          </div>
          <div className="bg-black/40 border border-white/10 p-2">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">Loop</div>
            <div className="font-mono text-slate-200 mt-1">{loopState}</div>
          </div>
          <div className="bg-black/40 border border-white/10 p-2">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">Source</div>
            <div className="font-mono text-slate-200 mt-1">{source}</div>
          </div>
        </div>
        <div className="bg-black/40 border border-white/10 p-2">
          <div className="text-[10px] uppercase tracking-widest text-slate-500">Commander</div>
          <div className="font-mono text-slate-200 mt-1">{awareness?.commander?.display_name || 'The Commander'}</div>
          <div className="text-[11px] text-slate-400 mt-1">
            {isCommander ? 'Control-plane node monitoring fleet status.' : 'Project node reporting into The Commander.'}
          </div>
        </div>
      </div>
    </DrawerCard>
  )
}
