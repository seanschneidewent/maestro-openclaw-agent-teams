import React from 'react'
import { DrawerCard, EmptyState, listOrEmpty } from './shared'

export default function ProjectDrawersSection({ drawers }) {
  if (!drawers || Object.keys(drawers).length === 0) return null

  return (
    <>
      <DrawerCard title="Operational Health">
        {drawers.operational_health ? (
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div className="bg-black/40 border border-white/10 p-2">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">% Complete</div>
              <div className="font-mono text-slate-100">{drawers.operational_health.percent_complete || 0}%</div>
            </div>
            <div className="bg-black/40 border border-white/10 p-2">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">SPI</div>
              <div className="font-mono text-slate-100">{drawers.operational_health.schedule_performance_index ?? 1}</div>
            </div>
            <div className="bg-black/40 border border-white/10 p-2">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">Variance</div>
              <div className="font-mono text-slate-100">{drawers.operational_health.variance_days || 0}D</div>
            </div>
            <div className="bg-black/40 border border-white/10 p-2">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">Weather Delays</div>
              <div className="font-mono text-slate-100">{drawers.operational_health.weather_delays || 0}</div>
            </div>
            <div className="col-span-2 bg-black/40 border border-white/10 p-2">
              <div className="text-[10px] uppercase tracking-widest text-slate-500">Notes</div>
              <div className="text-slate-300 text-xs mt-1">{drawers.operational_health.variance_notes || 'No notes'}</div>
            </div>
          </div>
        ) : (
          <EmptyState />
        )}
      </DrawerCard>

      <DrawerCard title="Critical Path & Constraints">
        {drawers.critical_path ? (
          <div className="space-y-3 text-xs">
            <div>
              <div className="text-slate-400 uppercase tracking-widest text-[10px] mb-1">Upcoming Critical Activities</div>
              {listOrEmpty(drawers.critical_path.upcoming_critical_activities, (item, idx) => (
                <div key={`${item.id || 'activity'}-${idx}`} className="bg-black/40 border border-white/10 p-2">
                  <div className="font-mono text-[#00e5ff]">{item.id || 'ACT'} · {item.name || 'Unnamed activity'}</div>
                  <div className="text-slate-300 mt-1">{Array.isArray(item.blockers) ? item.blockers.join(' | ') : (item.issue || 'No blockers listed')}</div>
                </div>
              ))}
            </div>
            <div>
              <div className="text-slate-400 uppercase tracking-widest text-[10px] mb-1">Constraints</div>
              {listOrEmpty(drawers.critical_path.constraints, (item, idx) => (
                <div key={`constraint-${idx}`} className="bg-black/40 border border-white/10 p-2">
                  <div className="font-mono text-slate-200">{item.activity_id || 'ACT'}</div>
                  <div className="text-slate-300 mt-1">{item.description || 'No description'}</div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <EmptyState />
        )}
      </DrawerCard>

      <DrawerCard title="RFI/Submittal Control">
        {drawers.rfi_submittal_control ? (
          <div className="space-y-3 text-xs">
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-black/40 border border-white/10 p-2">
                <div className="text-[10px] uppercase tracking-widest text-slate-500">Open RFIs</div>
                <div className="font-mono text-slate-100">{drawers.rfi_submittal_control.rfi_metrics?.open || 0}</div>
              </div>
              <div className="bg-black/40 border border-white/10 p-2">
                <div className="text-[10px] uppercase tracking-widest text-slate-500">Pending Submittals</div>
                <div className="font-mono text-slate-100">{drawers.rfi_submittal_control.submittal_metrics?.pending_review || 0}</div>
              </div>
            </div>
            <div>
              <div className="text-slate-400 uppercase tracking-widest text-[10px] mb-1">Top Open RFIs</div>
              {listOrEmpty(drawers.rfi_submittal_control.top_open_rfis, (item, idx) => (
                <div key={`${item.id || 'rfi'}-${idx}`} className="bg-black/40 border border-white/10 p-2">
                  <span className="font-mono text-[#00e5ff]">{item.id || 'RFI'}</span>
                  <span className="text-slate-300"> · {item.subject || 'No subject'}</span>
                </div>
              ))}
            </div>
            <div>
              <div className="text-slate-400 uppercase tracking-widest text-[10px] mb-1">Top Submittals</div>
              {listOrEmpty(drawers.rfi_submittal_control.top_submittals, (item, idx) => (
                <div key={`${item.id || 'sub'}-${idx}`} className="bg-black/40 border border-white/10 p-2">
                  <span className="font-mono text-[#00e5ff]">{item.id || 'SUB'}</span>
                  <span className="text-slate-300"> · {item.description || 'No description'}</span>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <EmptyState />
        )}
      </DrawerCard>

      <DrawerCard title="Decision & Exposure">
        {drawers.commercial_exposure ? (
          <div className="space-y-3 text-xs">
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-black/40 border border-white/10 p-2">
                <div className="text-[10px] uppercase tracking-widest text-slate-500">Pending COs</div>
                <div className="font-mono text-slate-100">{drawers.commercial_exposure.pending_change_orders || 0}</div>
              </div>
              <div className="bg-black/40 border border-white/10 p-2">
                <div className="text-[10px] uppercase tracking-widest text-slate-500">Exposure USD</div>
                <div className="font-mono text-slate-100">${drawers.commercial_exposure.total_exposure_usd || 0}</div>
              </div>
            </div>
            <div>
              <div className="text-slate-400 uppercase tracking-widest text-[10px] mb-1">Exposure Risks</div>
              {listOrEmpty(drawers.commercial_exposure.exposure_risks, (item, idx) => (
                <div key={`risk-${idx}`} className="bg-black/40 border border-white/10 p-2">
                  <div className="font-mono text-[#00e5ff]">{item.decision_id || 'DEC'}</div>
                  <div className="text-slate-300 mt-1">{item.description || 'No description'} · ${item.exposure_amount || 0}</div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <EmptyState />
        )}
      </DrawerCard>

      <DrawerCard title="Scope Gaps & Overlaps">
        {drawers.scope_watchlist ? (
          <div className="space-y-3 text-xs">
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-black/40 border border-white/10 p-2">
                <div className="text-[10px] uppercase tracking-widest text-slate-500">Gaps</div>
                <div className="font-mono text-slate-100">{drawers.scope_watchlist.metrics?.gaps || 0}</div>
              </div>
              <div className="bg-black/40 border border-white/10 p-2">
                <div className="text-[10px] uppercase tracking-widest text-slate-500">Overlaps</div>
                <div className="font-mono text-slate-100">{drawers.scope_watchlist.metrics?.overlaps || 0}</div>
              </div>
            </div>
            <div>
              <div className="text-slate-400 uppercase tracking-widest text-[10px] mb-1">Identified Gaps</div>
              {listOrEmpty(drawers.scope_watchlist.identified_gaps, (item, idx) => (
                <div key={`gap-${idx}`} className="bg-black/40 border border-white/10 p-2 text-slate-300">
                  {item.work_item || 'Unknown gap'}
                </div>
              ))}
            </div>
            <div>
              <div className="text-slate-400 uppercase tracking-widest text-[10px] mb-1">Identified Overlaps</div>
              {listOrEmpty(drawers.scope_watchlist.identified_overlaps, (item, idx) => (
                <div key={`overlap-${idx}`} className="bg-black/40 border border-white/10 p-2 text-slate-300">
                  {item.work_item || 'Unknown overlap'}
                </div>
              ))}
            </div>
          </div>
        ) : (
          <EmptyState />
        )}
      </DrawerCard>
    </>
  )
}

