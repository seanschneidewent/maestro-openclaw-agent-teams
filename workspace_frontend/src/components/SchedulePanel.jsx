import { useEffect, useMemo, useRef } from 'react'
import { CalendarClock, ChevronLeft, ChevronRight, RotateCcw } from 'lucide-react'
import MarkdownText from './MarkdownText'

function statusPill(status) {
  const clean = String(status || '').toLowerCase()
  if (clean === 'blocked') return 'bg-amber-50 text-amber-700 border border-amber-200'
  if (clean === 'in_progress') return 'bg-indigo-50 text-indigo-700 border border-indigo-200'
  if (clean === 'done') return 'bg-emerald-50 text-emerald-700 border border-emerald-200'
  if (clean === 'cancelled') return 'bg-slate-100 text-slate-600 border border-slate-300'
  return 'bg-cyan-50 text-cyan-700 border border-cyan-200'
}

function ScheduleItemCard({ item }) {
  const title = String(item?.title || item?.id || 'Untitled item')
  const description = String(item?.description || '').trim()
  const owner = String(item?.owner || '').trim()
  const status = String(item?.status || 'pending')

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-xs font-medium text-slate-800 break-words">{title}</p>
          {description ? <MarkdownText content={description} size="tiny" className="mt-1 text-slate-600" /> : null}
        </div>
        <span className={`text-[10px] px-2 py-0.5 rounded-full uppercase tracking-wide whitespace-nowrap ${statusPill(status)}`}>
          {status.replace(/_/g, ' ')}
        </span>
      </div>
      {owner ? (
        <p className="text-[11px] text-slate-500 mt-1">Owner: {owner}</p>
      ) : null}
    </div>
  )
}

export default function SchedulePanel({
  scheduleTimeline,
  scheduleMonth,
  loading,
  error,
  onRefresh,
  onPrevMonth,
  onNextMonth,
  onToday,
}) {
  const listRef = useRef(null)
  const todayRef = useRef(null)
  const centeredKeyRef = useRef('')

  const days = useMemo(
    () => (Array.isArray(scheduleTimeline?.days) ? scheduleTimeline.days : []),
    [scheduleTimeline],
  )
  const unscheduled = useMemo(
    () => (Array.isArray(scheduleTimeline?.unscheduled) ? scheduleTimeline.unscheduled : []),
    [scheduleTimeline],
  )

  useEffect(() => {
    if (!days.length || !listRef.current) return
    const centerKey = `${scheduleTimeline?.month || scheduleTimeline?.today || ''}:${days.length}`
    if (centeredKeyRef.current === centerKey) return

    const container = listRef.current
    const target = todayRef.current
    if (target) {
      const nextTop = target.offsetTop - (container.clientHeight / 2) + (target.clientHeight / 2)
      container.scrollTop = Math.max(0, nextTop)
    } else {
      container.scrollTop = 0
    }
    centeredKeyRef.current = centerKey
  }, [days, scheduleTimeline?.today, scheduleTimeline?.month])

  const monthTitle = String(scheduleTimeline?.month_label || scheduleMonth || 'Schedule')
  const selectedMonth = String(scheduleTimeline?.month || scheduleMonth || '')
  const currentMonth = String(scheduleTimeline?.today || '').slice(0, 7)
  const isCurrentMonth = Boolean(selectedMonth && currentMonth && selectedMonth === currentMonth)

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <div className="flex items-center gap-2">
            <CalendarClock size={14} className="text-cyan-700" />
            <h3 className="text-sm font-semibold text-slate-800">Project Schedule</h3>
          </div>
          <p className="text-xs text-slate-500 mt-1">Today is centered by default when visible. Scroll up for future and down for past.</p>
          <div className="mt-2 inline-flex items-center rounded-lg border border-slate-300 bg-white overflow-hidden">
            <button
              type="button"
              onClick={onPrevMonth}
              className="h-7 w-7 inline-flex items-center justify-center text-slate-600 hover:bg-slate-50"
              title="Previous month"
            >
              <ChevronLeft size={14} />
            </button>
            <div className="px-2 text-xs font-medium text-slate-700 min-w-32 text-center">{monthTitle}</div>
            <button
              type="button"
              onClick={onNextMonth}
              className="h-7 w-7 inline-flex items-center justify-center text-slate-600 hover:bg-slate-50"
              title="Next month"
            >
              <ChevronRight size={14} />
            </button>
          </div>
          {!isCurrentMonth ? (
            <button
              type="button"
              onClick={onToday}
              className="ml-2 mt-2 inline-flex items-center gap-1 text-xs px-2 py-1 rounded border border-cyan-300 bg-cyan-50 text-cyan-700 hover:bg-cyan-100"
            >
              Jump To Today
            </button>
          ) : null}
        </div>
        <button
          type="button"
          onClick={onRefresh}
          className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded border border-slate-300 hover:bg-slate-50 text-slate-700"
          title="Refresh schedule"
        >
          <RotateCcw size={12} />
          Refresh
        </button>
      </div>

      {error ? (
        <div className="mb-3 text-xs text-rose-600 bg-rose-50 border border-rose-200 rounded px-2 py-1.5">
          {error}
        </div>
      ) : null}

      <div ref={listRef} className="max-h-[56vh] overflow-auto pr-1">
        {loading ? (
          <div className="text-xs text-slate-400">Loading schedule…</div>
        ) : days.length === 0 ? (
          <div className="text-xs text-slate-400">No schedule days found.</div>
        ) : (
          <div className="space-y-2">
            {days.map((day, index) => {
              const previous = index > 0 ? days[index - 1] : null
              const weekChanged = !previous || String(previous.week_start || '') !== String(day.week_start || '')
              const dayItems = Array.isArray(day?.items) ? day.items : []
              const periodLabel = day.is_today ? 'Today' : day.is_future ? 'Future' : 'Past'

              return (
                <div key={day.date || `schedule-day-${index}`}>
                  {weekChanged ? (
                    <div className="border-t-2 border-slate-300 pt-2 mt-3 first:mt-0">
                      <p className="text-[10px] uppercase tracking-[0.12em] text-slate-500 font-semibold">
                        {day.week_label || 'Week'}
                      </p>
                    </div>
                  ) : null}

                  <section
                    ref={day.is_today ? todayRef : undefined}
                    className={`rounded-xl border p-2.5 ${day.is_today ? 'border-cyan-300 bg-cyan-50/40' : 'border-slate-200 bg-white'}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-xs font-semibold text-slate-800">{day.label || day.date}</p>
                      <span className="text-[10px] uppercase tracking-wide text-slate-500">{periodLabel}</span>
                    </div>

                    <div className="mt-2 space-y-1.5">
                      {dayItems.length === 0 ? (
                        <p className="text-xs text-slate-400">No scheduled items.</p>
                      ) : (
                        dayItems.map((item) => (
                          <ScheduleItemCard key={item.id || `${day.date}-${item.title}`} item={item} />
                        ))
                      )}
                    </div>
                  </section>
                </div>
              )
            })}

            {unscheduled.length > 0 ? (
              <div className="border-t border-slate-200 pt-3 mt-2">
                <p className="text-[10px] uppercase tracking-[0.12em] text-slate-500 font-semibold mb-2">Unscheduled</p>
                <div className="space-y-1.5">
                  {unscheduled.map((item) => (
                    <ScheduleItemCard key={item.id || `unscheduled-${item.title}`} item={item} />
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        )}
      </div>
    </div>
  )
}
