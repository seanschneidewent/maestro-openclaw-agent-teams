import React, { useEffect, useMemo, useState } from 'react'
import { api } from '../../lib/api'
import { DrawerCard } from './shared'

function TimelineItem({ item }) {
  const itemType = String(item?.type || 'task').replaceAll('_', ' ')
  const status = String(item?.status || 'pending').replaceAll('_', ' ')
  return (
    <div className="border border-white/10 bg-black/30 p-2 text-[11px]">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[#00e5ff]">{item?.title || item?.id || 'Untitled item'}</span>
        <span className="text-slate-500 uppercase tracking-widest">{status}</span>
      </div>
      <div className="text-slate-400 mt-1">
        {itemType}
        {item?.owner ? ` · owner ${item.owner}` : ''}
      </div>
    </div>
  )
}

export default function ScheduleSection({ isCommander, hasProjectStore, projectSlug }) {
  const [timeline, setTimeline] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [month, setMonth] = useState('')

  useEffect(() => {
    let cancelled = false
    if (isCommander || !hasProjectStore || !projectSlug) {
      setTimeline(null)
      setLoading(false)
      setError('')
      return () => {}
    }

    async function loadTimeline() {
      setLoading(true)
      setError('')
      try {
        const payload = await api.getProjectScheduleTimeline(projectSlug, { month, includeEmptyDays: true })
        if (cancelled) return
        setTimeline(payload || null)
      } catch (loadError) {
        if (cancelled) return
        setTimeline(null)
        setError(loadError?.message || 'Failed to load schedule timeline')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    loadTimeline()
    return () => {
      cancelled = true
    }
  }, [hasProjectStore, isCommander, month, projectSlug])

  const days = useMemo(
    () => (Array.isArray(timeline?.days) ? timeline.days : []),
    [timeline?.days],
  )

  if (isCommander) {
    return (
      <DrawerCard title="Schedule" className="xl:col-span-2">
        <div className="text-xs text-slate-400">
          Commander does not own a project schedule. Use project node timelines.
        </div>
      </DrawerCard>
    )
  }

  if (!hasProjectStore) {
    return (
      <DrawerCard title="Schedule" className="xl:col-span-2">
        <div className="text-xs text-slate-400">
          This node is not bound to a project store yet.
        </div>
      </DrawerCard>
    )
  }

  return (
    <DrawerCard title="Schedule" className="xl:col-span-2">
      <div className="space-y-2 text-xs">
        <div className="flex items-center justify-between bg-black/40 border border-white/10 p-2">
          <button
            type="button"
            className="border border-white/20 px-2 py-1 text-[10px] uppercase tracking-widest hover:border-[#00e5ff] hover:text-[#00e5ff]"
            disabled={!timeline?.previous_month || loading}
            onClick={() => setMonth(String(timeline?.previous_month || ''))}
          >
            Prev
          </button>
          <div className="text-slate-200 font-mono">{timeline?.month_label || 'Schedule Timeline'}</div>
          <button
            type="button"
            className="border border-white/20 px-2 py-1 text-[10px] uppercase tracking-widest hover:border-[#00e5ff] hover:text-[#00e5ff]"
            disabled={!timeline?.next_month || loading}
            onClick={() => setMonth(String(timeline?.next_month || ''))}
          >
            Next
          </button>
        </div>
        {loading && <div className="text-slate-500">Loading timeline...</div>}
        {error && <div className="text-rose-300">{error}</div>}
        {!loading && !error && (
          <div className="max-h-80 overflow-auto space-y-2 pr-1">
            {days.length === 0 ? (
              <div className="text-slate-500">No schedule entries for this month.</div>
            ) : (
              days.map((day) => (
                <div key={day.date} className="border border-white/10 bg-black/25 p-2">
                  <div className="flex items-center justify-between mb-1">
                    <span className={`font-mono ${day.is_today ? 'text-[#00e5ff]' : 'text-slate-300'}`}>{day.label}</span>
                    <span className="text-slate-500">{day.item_count || 0} item(s)</span>
                  </div>
                  {Array.isArray(day.items) && day.items.length > 0 ? (
                    <div className="space-y-1">
                      {day.items.map((item) => (
                        <TimelineItem key={item.id || `${day.date}-${item.title}`} item={item} />
                      ))}
                    </div>
                  ) : (
                    <div className="text-slate-600">No entries.</div>
                  )}
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </DrawerCard>
  )
}
