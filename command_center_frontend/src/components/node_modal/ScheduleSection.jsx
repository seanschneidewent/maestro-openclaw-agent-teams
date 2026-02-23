import React from 'react'
import { DrawerCard } from './shared'

function fmtNumber(value, fallback = '0') {
  const n = Number(value)
  if (Number.isNaN(n)) return fallback
  return String(n)
}

export default function ScheduleSection({ isCommander, detail, statusPayload }) {
  if (isCommander) {
    return (
      <DrawerCard title="Schedule" className="xl:col-span-2">
        <div className="text-xs text-slate-400">
          Commander node does not run a project schedule directly.
        </div>
      </DrawerCard>
    )
  }

  const report = statusPayload?.status_report || {}
  const heartbeat = statusPayload?.heartbeat || {}
  const operational = detail?.drawers?.operational_health || {}
  const critical = detail?.drawers?.critical_path || {}
  const upcoming = Array.isArray(critical?.upcoming_critical_activities) ? critical.upcoming_critical_activities : []
  const constraints = Array.isArray(critical?.constraints) ? critical.constraints : []

  return (
    <DrawerCard title="Schedule" className="xl:col-span-2">
      <div className="space-y-3 text-xs">
        <div className="bg-black/40 border border-white/10 p-2">
          <div className="text-[10px] uppercase tracking-widest text-slate-500">Summary</div>
          <div className="text-slate-200 mt-1">{report.summary || 'No schedule summary yet.'}</div>
          <div className="text-[10px] uppercase tracking-widest text-slate-500 mt-2">
            Source: <span className="text-slate-300 font-mono">{report.source || 'computed'}</span>
            {heartbeat.available && !heartbeat.is_fresh && (
              <span className="text-amber-400 ml-2">HEARTBEAT STALE</span>
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <div className="bg-black/40 border border-white/10 p-2">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">% Complete</div>
            <div className="font-mono text-slate-200 mt-1">{fmtNumber(operational.percent_complete)}%</div>
          </div>
          <div className="bg-black/40 border border-white/10 p-2">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">SPI</div>
            <div className="font-mono text-slate-200 mt-1">{fmtNumber(operational.schedule_performance_index, '1')}</div>
          </div>
          <div className="bg-black/40 border border-white/10 p-2">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">Variance</div>
            <div className="font-mono text-slate-200 mt-1">{fmtNumber(operational.variance_days)}d</div>
          </div>
          <div className="bg-black/40 border border-white/10 p-2">
            <div className="text-[10px] uppercase tracking-widest text-slate-500">Constraints</div>
            <div className="font-mono text-slate-200 mt-1">{constraints.length}</div>
          </div>
        </div>

        <div className="bg-black/40 border border-white/10 p-2">
          <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Upcoming Critical</div>
          {upcoming.length === 0 ? (
            <div className="text-slate-500">No upcoming critical activities.</div>
          ) : (
            <div className="space-y-1.5">
              {upcoming.slice(0, 4).map((item, idx) => (
                <div key={`${item?.id || 'act'}-${idx}`} className="border border-white/10 bg-black/30 p-2">
                  <div className="font-mono text-[#00e5ff]">{item?.id || 'ACT'} · {item?.name || 'Unnamed activity'}</div>
                  {Array.isArray(item?.blockers) && item.blockers.length > 0 && (
                    <div className="text-slate-300 mt-1">{item.blockers.join(' | ')}</div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </DrawerCard>
  )
}

