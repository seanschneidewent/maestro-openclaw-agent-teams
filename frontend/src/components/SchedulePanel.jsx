import { useMemo, useState } from 'react'
import { CalendarClock, CheckCircle2, AlertTriangle, Plus, RotateCcw } from 'lucide-react'

const ITEM_TYPES = ['activity', 'milestone', 'constraint', 'inspection', 'delivery', 'task']
const ACTIVE_STATUSES = ['pending', 'in_progress', 'blocked']

function statusPill(status) {
  const clean = String(status || '').toLowerCase()
  if (clean === 'blocked') return 'bg-amber-50 text-amber-700 border border-amber-200'
  if (clean === 'in_progress') return 'bg-indigo-50 text-indigo-700 border border-indigo-200'
  if (clean === 'done') return 'bg-emerald-50 text-emerald-700 border border-emerald-200'
  if (clean === 'cancelled') return 'bg-slate-100 text-slate-600 border border-slate-300'
  return 'bg-cyan-50 text-cyan-700 border border-cyan-200'
}

export default function SchedulePanel({
  scheduleStatus,
  scheduleItems,
  loading,
  error,
  onRefresh,
  onCreateItem,
  onCloseItem,
}) {
  const [title, setTitle] = useState('')
  const [itemType, setItemType] = useState('activity')
  const [dueDate, setDueDate] = useState('')
  const [owner, setOwner] = useState('')
  const [saving, setSaving] = useState(false)

  const items = Array.isArray(scheduleItems) ? scheduleItems : []
  const activeItems = useMemo(
    () => items.filter((item) => ACTIVE_STATUSES.includes(String(item?.status || '').toLowerCase())),
    [items],
  )

  const current = scheduleStatus?.current || {}
  const lookahead = scheduleStatus?.lookahead || {}

  const submit = async (event) => {
    event.preventDefault()
    const cleanTitle = String(title || '').trim()
    if (!cleanTitle) return
    setSaving(true)
    try {
      await onCreateItem({
        title: cleanTitle,
        type: itemType,
        status: itemType === 'constraint' ? 'blocked' : 'pending',
        due_date: dueDate || undefined,
        owner: owner || undefined,
      })
      setTitle('')
      setDueDate('')
      setOwner('')
      setItemType('activity')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <div className="flex items-center gap-2">
            <CalendarClock size={14} className="text-cyan-700" />
            <h3 className="text-sm font-semibold text-slate-800">Schedule</h3>
          </div>
          <p className="text-xs text-slate-500 mt-1">{scheduleStatus?.summary || 'No schedule summary yet.'}</p>
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

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3">
        <div className="bg-slate-50 border border-slate-200 rounded px-2 py-1.5">
          <div className="text-[11px] text-slate-500">Complete</div>
          <div className="font-semibold text-slate-800">{Number(current.percent_complete || 0)}%</div>
        </div>
        <div className="bg-slate-50 border border-slate-200 rounded px-2 py-1.5">
          <div className="text-[11px] text-slate-500">SPI</div>
          <div className="font-semibold text-slate-800">{Number(current.schedule_performance_index || 1).toFixed(2)}</div>
        </div>
        <div className="bg-slate-50 border border-slate-200 rounded px-2 py-1.5">
          <div className="text-[11px] text-slate-500">Variance</div>
          <div className="font-semibold text-slate-800">{Number(current.variance_days || 0)}d</div>
        </div>
        <div className="bg-slate-50 border border-slate-200 rounded px-2 py-1.5">
          <div className="text-[11px] text-slate-500">Constraints</div>
          <div className="font-semibold text-slate-800">{Number(lookahead.constraint_count || 0)}</div>
        </div>
      </div>

      {error && (
        <div className="mb-3 text-xs text-rose-600 bg-rose-50 border border-rose-200 rounded px-2 py-1.5">
          {error}
        </div>
      )}

      <div className="mb-3">
        <div className="text-xs font-medium text-slate-700 mb-2">Active Items</div>
        <div className="max-h-52 overflow-auto space-y-1.5 pr-1">
          {loading ? (
            <div className="text-xs text-slate-400">Loading schedule…</div>
          ) : activeItems.length === 0 ? (
            <div className="text-xs text-slate-400">No active schedule items.</div>
          ) : (
            activeItems.slice(0, 10).map((item) => (
              <div key={item.id} className="border border-slate-200 rounded-lg p-2 bg-slate-50">
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="text-xs font-medium text-slate-800 truncate">{item.title || item.id}</div>
                    <div className="text-[11px] text-slate-500 mt-0.5">
                      {item.type || 'activity'}
                      {item.owner ? ` · owner ${item.owner}` : ''}
                      {item.due_date ? ` · due ${item.due_date}` : ''}
                    </div>
                  </div>
                  <span className={`text-[10px] px-2 py-0.5 rounded-full uppercase tracking-wide ${statusPill(item.status)}`}>
                    {item.status}
                  </span>
                </div>
                <div className="mt-2 flex gap-2">
                  <button
                    type="button"
                    onClick={() => onCloseItem(item.id, { status: 'done', reason: 'Closed from workspace panel' })}
                    className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded border border-emerald-300 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                  >
                    <CheckCircle2 size={11} />
                    Done
                  </button>
                  <button
                    type="button"
                    onClick={() => onCloseItem(item.id, { status: 'cancelled', reason: 'Cancelled from workspace panel' })}
                    className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded border border-slate-300 bg-white text-slate-600 hover:bg-slate-100"
                  >
                    <AlertTriangle size={11} />
                    Cancel
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      <form onSubmit={submit} className="border-t border-slate-200 pt-3 space-y-2">
        <div className="text-xs font-medium text-slate-700">Add Schedule Item</div>
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Item title"
          className="w-full border border-slate-300 rounded px-2 py-1.5 text-xs"
        />
        <div className="grid grid-cols-2 gap-2">
          <select
            value={itemType}
            onChange={(event) => setItemType(event.target.value)}
            className="border border-slate-300 rounded px-2 py-1.5 text-xs"
          >
            {ITEM_TYPES.map((type) => (
              <option key={type} value={type}>{type}</option>
            ))}
          </select>
          <input
            value={dueDate}
            onChange={(event) => setDueDate(event.target.value)}
            placeholder="YYYY-MM-DD"
            className="border border-slate-300 rounded px-2 py-1.5 text-xs"
          />
        </div>
        <input
          value={owner}
          onChange={(event) => setOwner(event.target.value)}
          placeholder="Owner (optional)"
          className="w-full border border-slate-300 rounded px-2 py-1.5 text-xs"
        />
        <button
          type="submit"
          disabled={saving || !String(title || '').trim()}
          className="inline-flex items-center gap-1 text-xs px-3 py-1.5 rounded border border-cyan-300 bg-cyan-50 text-cyan-700 hover:bg-cyan-100 disabled:opacity-50"
        >
          <Plus size={12} />
          {saving ? 'Saving...' : 'Add Item'}
        </button>
      </form>
    </div>
  )
}

