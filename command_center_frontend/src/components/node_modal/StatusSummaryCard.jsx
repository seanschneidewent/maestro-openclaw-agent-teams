import React from 'react'

export default function StatusSummaryCard({ status }) {
  const report = status?.status_report || {}
  const metrics = report?.metrics || {}
  return (
    <div className="space-y-2 text-xs">
      <div className="bg-black/40 border border-white/10 p-2">
        <div className="text-[10px] uppercase tracking-widest text-slate-500">Summary ({report.source || 'computed'})</div>
        <div className="text-slate-200 mt-1">{report.summary || 'No status summary yet.'}</div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div className="bg-black/40 border border-white/10 p-2">
          <div className="text-[10px] uppercase tracking-widest text-slate-500">Attention</div>
          <div className="font-mono text-slate-100">{metrics.attention_score || 0}</div>
        </div>
        <div className="bg-black/40 border border-white/10 p-2">
          <div className="text-[10px] uppercase tracking-widest text-slate-500">Loop</div>
          <div className="font-mono text-slate-100">{report.loop_state || 'idle'}</div>
        </div>
      </div>
    </div>
  )
}

