import SchedulePanel from './SchedulePanel'

export default function ScheduleSheet({
  open,
  scheduleTimeline,
  scheduleMonth,
  scheduleLoading,
  scheduleError,
  onScheduleRefresh,
  onScheduleMonthPrev,
  onScheduleMonthNext,
  onScheduleMonthToday,
}) {
  return (
    <section
      className={`fixed inset-x-2 top-3 bottom-20 z-40 rounded-2xl border border-slate-200 bg-white shadow-2xl transition-all duration-200 ${
        open ? 'translate-y-0 opacity-100 pointer-events-auto' : 'translate-y-[110%] opacity-0 pointer-events-none'
      }`}
      role="dialog"
      aria-modal="true"
      aria-label="Schedule panel"
    >
      <div className="h-full overflow-hidden p-3 bg-gradient-to-b from-slate-50 to-white rounded-2xl">
        <SchedulePanel
          scheduleTimeline={scheduleTimeline}
          scheduleMonth={scheduleMonth}
          loading={scheduleLoading}
          error={scheduleError}
          onRefresh={onScheduleRefresh || (() => {})}
          onPrevMonth={onScheduleMonthPrev || (() => {})}
          onNextMonth={onScheduleMonthNext || (() => {})}
          onToday={onScheduleMonthToday || (() => {})}
        />
      </div>
    </section>
  )
}
