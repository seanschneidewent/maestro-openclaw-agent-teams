import { CalendarClock, MessageSquare, X } from 'lucide-react'
import SchedulePanel from './SchedulePanel'

function NoteCard({ note }) {
  return (
    <div className="border border-amber-200 bg-amber-50/60 rounded-xl px-4 py-3">
      <div className="flex items-start gap-2">
        <MessageSquare size={13} className="text-amber-600 mt-0.5 shrink-0" />
        <div>
          <p className="text-sm text-slate-700 leading-relaxed">{note.text}</p>
          {note.source_page && (
            <p className="text-xs text-slate-500 mt-1.5">Source: {note.source_page}</p>
          )}
        </div>
      </div>
    </div>
  )
}

export default function StatusSheet({
  open,
  activeTab,
  onTabChange,
  onClose,
  workspaceTitle,
  notes,
  scheduleStatus,
  scheduleItems,
  scheduleLoading,
  scheduleError,
  onScheduleRefresh,
  onScheduleCreate,
  onScheduleClose,
}) {
  const noteItems = Array.isArray(notes) ? notes : []

  return (
    <section
      className={`fixed left-1/2 bottom-24 z-40 w-[min(70rem,calc(100vw-1.5rem))] -translate-x-1/2 rounded-2xl border border-slate-200 bg-white shadow-2xl transition-all duration-200 ${
        open ? 'translate-y-0 opacity-100 pointer-events-auto' : 'translate-y-[110%] opacity-0 pointer-events-none'
      }`}
      role="dialog"
      aria-modal="true"
      aria-label="Status panel"
    >
      <div className="px-4 py-3 border-b border-slate-200 bg-white/95 backdrop-blur-sm rounded-t-2xl flex items-center justify-between">
        <div className="min-w-0">
          <p className="text-[11px] uppercase tracking-widest text-slate-500 font-medium">AI Managed Status</p>
          <p className="text-sm text-slate-700 truncate">{workspaceTitle || 'No workspace selected'}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="p-1.5 rounded-md border border-slate-300 text-slate-600 hover:bg-slate-50"
          title="Close status panel"
        >
          <X size={14} />
        </button>
      </div>

      <div className="px-4 pt-3 pb-2 border-b border-slate-200 flex items-center gap-2">
        <button
          type="button"
          onClick={() => onTabChange('schedule')}
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs border ${
            activeTab === 'schedule'
              ? 'bg-cyan-50 border-cyan-300 text-cyan-700'
              : 'bg-white border-slate-300 text-slate-600 hover:bg-slate-50'
          }`}
        >
          <CalendarClock size={12} />
          Schedule
        </button>
        <button
          type="button"
          onClick={() => onTabChange('notes')}
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs border ${
            activeTab === 'notes'
              ? 'bg-amber-50 border-amber-300 text-amber-700'
              : 'bg-white border-slate-300 text-slate-600 hover:bg-slate-50'
          }`}
        >
          <MessageSquare size={12} />
          Notes
        </button>
      </div>

      <div className="max-h-[65vh] overflow-auto p-4 bg-gradient-to-b from-slate-50 to-white rounded-b-2xl">
        {activeTab === 'schedule' ? (
          <SchedulePanel
            scheduleStatus={scheduleStatus}
            scheduleItems={scheduleItems}
            loading={scheduleLoading}
            error={scheduleError}
            onRefresh={onScheduleRefresh || (() => {})}
            onCreateItem={onScheduleCreate || (async () => {})}
            onCloseItem={onScheduleClose || (async () => {})}
          />
        ) : (
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <div className="flex items-center gap-2 mb-3">
              <MessageSquare size={14} className="text-amber-600" />
              <h3 className="text-sm font-semibold text-slate-800">Notes</h3>
            </div>
            {noteItems.length === 0 ? (
              <p className="text-xs text-slate-400">No notes yet.</p>
            ) : (
              <div className="space-y-2">
                {noteItems.map((note, index) => (
                  <NoteCard key={`status-note-${index}`} note={note} />
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  )
}
