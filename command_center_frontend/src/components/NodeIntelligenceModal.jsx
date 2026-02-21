import React, { useEffect, useRef, useState } from 'react'

function DrawerCard({ title, children, className = '' }) {
  return (
    <section className={`border border-white/10 bg-black/40 p-4 ${className}`}>
      <h3 className="text-xs uppercase tracking-widest font-mono text-[#00e5ff] mb-3">{title}</h3>
      {children}
    </section>
  )
}

function EmptyState() {
  return <div className="text-sm text-slate-500">No data available.</div>
}

function listOrEmpty(items, renderFn) {
  if (!Array.isArray(items) || items.length === 0) {
    return <EmptyState />
  }
  return <div className="space-y-2">{items.map(renderFn)}</div>
}

export default function NodeIntelligenceModal({ project, detail, awareness, control, onClose }) {
  const panelRef = useRef(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    const panel = panelRef.current
    if (!panel) return undefined

    const focusable = panel.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    )
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (first) first.focus()

    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key === 'Tab' && focusable.length > 1) {
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault()
          last.focus()
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault()
          first.focus()
        }
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const drawers = detail?.drawers || {}
  const preflightChecks = Array.isArray(control?.preflight?.checks) ? control.preflight.checks : []

  const copyCommand = async () => {
    const command = control?.ingest?.command
    if (!command) return
    try {
      await navigator.clipboard.writeText(command)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1200)
    } catch (error) {
      console.error('Failed to copy command', error)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
      role="presentation"
    >
      <div
        ref={panelRef}
        className="w-full h-full md:h-auto md:max-h-[90vh] md:max-w-6xl overflow-auto bg-[#05080f] border border-[#00e5ff]/30 p-5 md:p-6"
        role="dialog"
        aria-modal="true"
        aria-label={`Node Intelligence - ${project.name}`}
      >
        <div className="flex justify-between items-start mb-5 gap-4">
          <div>
            <p className="text-[10px] uppercase tracking-widest font-mono text-slate-500">Node Intelligence Drawer</p>
            <h2 className="text-xl md:text-2xl text-white uppercase tracking-widest mt-1">{project.name}</h2>
            <p className="text-xs text-slate-400 mt-1">
              Attention Score <span className="text-[#00e5ff] font-mono">{project.attention_score || 0}</span>
              {' · '}
              Last Updated <span className="text-slate-300 font-mono">{project.last_updated || '—'}</span>
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="border border-white/20 text-slate-300 px-3 py-1.5 text-xs uppercase tracking-widest font-mono hover:border-[#00e5ff] hover:text-[#00e5ff]"
          >
            Close
          </button>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
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
                <div className="bg-black/40 border border-white/10 p-2">
                  <div className="text-[10px] uppercase tracking-widest text-slate-500">Gateway Auth</div>
                  <div className={`font-mono ${awareness?.services?.openclaw?.gateway_auth?.tokens_aligned ? 'text-[#00e676]' : 'text-amber-400'}`}>
                    {awareness?.services?.openclaw?.gateway_auth?.tokens_aligned ? 'ALIGNED' : 'MISALIGNED'}
                  </div>
                </div>
                <div className="bg-black/40 border border-white/10 p-2">
                  <div className="text-[10px] uppercase tracking-widest text-slate-500">CLI Pairing</div>
                  <div className={`font-mono ${awareness?.services?.openclaw?.device_pairing?.required ? 'text-amber-400' : 'text-[#00e676]'}`}>
                    {awareness?.services?.openclaw?.device_pairing?.required ? 'REQUIRED' : 'HEALTHY'}
                  </div>
                </div>
              </div>
              <div className="space-y-2">
                <div className="bg-black/40 border border-white/10 p-2">
                  <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Ingest Command</div>
                  <code className="block text-[11px] leading-relaxed text-slate-200 break-words">{control?.ingest?.command || 'Unavailable'}</code>
                  <div className="mt-2 flex items-center gap-2">
                    <button
                      type="button"
                      onClick={copyCommand}
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
              </div>
            </div>
          </DrawerCard>

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
        </div>
      </div>
    </div>
  )
}
