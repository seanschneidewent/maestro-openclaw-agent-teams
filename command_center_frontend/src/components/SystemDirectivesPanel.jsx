import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import MarkdownText from './MarkdownText'

const DEFAULT_FORM = {
  id: '',
  title: '',
  body: '',
  scope: 'global',
  priority: 70,
  status: 'active',
  tags: '',
}

function statusTone(status) {
  const lowered = String(status || '').toLowerCase()
  if (lowered === 'active') return 'text-[#00e676] border-[#00e676]/30 bg-[#00e676]/10'
  if (lowered === 'draft') return 'text-amber-300 border-amber-300/30 bg-amber-300/10'
  if (lowered === 'superseded') return 'text-orange-300 border-orange-300/30 bg-orange-300/10'
  if (lowered === 'archived') return 'text-slate-400 border-slate-400/30 bg-slate-400/10'
  return 'text-slate-300 border-white/20 bg-white/5'
}

export default function SystemDirectivesPanel({ onChanged, availableActions = [], fallbackDirectives = [] }) {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [showArchived, setShowArchived] = useState(false)
  const [showComposer, setShowComposer] = useState(false)
  const [form, setForm] = useState(DEFAULT_FORM)

  const actionSet = useMemo(() => new Set(Array.isArray(availableActions) ? availableActions : []), [availableActions])
  const canList = actionSet.has('list_system_directives')
  const canUpsert = actionSet.has('upsert_system_directive')
  const canArchive = actionSet.has('archive_system_directive')

  const mappedFallbackDirectives = useMemo(
    () =>
      (Array.isArray(fallbackDirectives) ? fallbackDirectives : []).map((item) => ({
        id: item.id,
        title: item.title || item.id || 'Directive',
        body: item.command || item.body || '',
        status: item.status || 'active',
        scope: item.scope || 'global',
        priority: item.priority ?? 50,
        updated_at: item.timestamp || '',
      })),
    [fallbackDirectives],
  )

  const loadFromApi = useCallback(async () => {
    if (!canList) return
    setLoading(true)
    setError('')
    try {
      const payload = await api.listSystemDirectives(showArchived)
      setItems(Array.isArray(payload?.directives) ? payload.directives : [])
    } catch (err) {
      setError(err?.message || 'Failed to load directives')
    } finally {
      setLoading(false)
    }
  }, [canList, showArchived])

  useEffect(() => {
    if (!canList) {
      setLoading(false)
      setError('')
      setItems(
        showArchived
          ? mappedFallbackDirectives
          : mappedFallbackDirectives.filter((item) => String(item.status || '').toLowerCase() !== 'archived'),
      )
    }
  }, [canList, mappedFallbackDirectives, showArchived])

  useEffect(() => {
    if (canList) {
      loadFromApi()
    }
  }, [canList, loadFromApi])

  const activeCount = useMemo(
    () => items.filter((item) => String(item?.status || '').toLowerCase() === 'active').length,
    [items],
  )

  async function saveDirective(event) {
    event.preventDefault()
    if (!canUpsert) {
      setError('This server build is read-only for directives. Run `maestro update` and restart `maestro up`.')
      return
    }
    if (!form.title.trim() || !form.body.trim()) {
      setError('Directive title and body are required.')
      return
    }

    setSaving(true)
    setError('')
    try {
      const tags = form.tags
        .split(',')
        .map((entry) => entry.trim())
        .filter(Boolean)
      await api.upsertSystemDirective({
        id: form.id.trim() || undefined,
        title: form.title.trim(),
        body: form.body.trim(),
        scope: form.scope.trim() || 'global',
        priority: Number(form.priority) || 50,
        status: form.status,
        tags,
      })
      setForm(DEFAULT_FORM)
      setShowComposer(false)
      if (canList) {
        await loadFromApi()
      }
      if (onChanged) await onChanged()
    } catch (err) {
      setError(err?.message || 'Failed to save directive')
    } finally {
      setSaving(false)
    }
  }

  async function archiveDirective(id) {
    if (!id) return
    if (!canArchive) {
      setError('This server build cannot archive directives yet. Run `maestro update` and restart `maestro up`.')
      return
    }
    setSaving(true)
    setError('')
    try {
      await api.archiveSystemDirective(id)
      if (canList) {
        await loadFromApi()
      }
      if (onChanged) await onChanged()
    } catch (err) {
      setError(err?.message || 'Failed to archive directive')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="border border-white/10 bg-black/40 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-xs tracking-[0.2em] uppercase text-white">System Directives</h3>
          <p className="text-[10px] text-slate-500 font-mono uppercase tracking-widest mt-1">
            {activeCount} Active
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="text-[10px] px-2 py-1 border border-white/20 text-slate-300 hover:border-[#00e5ff]/60 hover:text-[#00e5ff] transition-colors"
            onClick={() => setShowArchived((prev) => !prev)}
          >
            {showArchived ? 'Hide Archived' : 'Show Archived'}
          </button>
          <button
            type="button"
            className="text-[10px] px-2 py-1 border border-[#00e5ff]/40 text-[#00e5ff] hover:bg-[#00e5ff]/10 transition-colors"
            onClick={() => {
              if (!canUpsert) {
                setError('Directive create/update is unavailable on this running server build.')
                return
              }
              setShowComposer((prev) => !prev)
            }}
          >
            {showComposer ? 'Close' : 'New Directive'}
          </button>
        </div>
      </div>

      {showComposer && (
        <form onSubmit={saveDirective} className="space-y-2 border border-white/10 bg-[#0a0e17] p-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            <input
              placeholder="Title"
              value={form.title}
              onChange={(event) => setForm((prev) => ({ ...prev, title: event.target.value }))}
              className="bg-black/40 border border-white/15 px-2 py-1 text-xs text-slate-200"
            />
            <input
              placeholder="ID (optional)"
              value={form.id}
              onChange={(event) => setForm((prev) => ({ ...prev, id: event.target.value }))}
              className="bg-black/40 border border-white/15 px-2 py-1 text-xs text-slate-200 font-mono"
            />
          </div>
          <textarea
            placeholder="Directive body / policy text"
            value={form.body}
            onChange={(event) => setForm((prev) => ({ ...prev, body: event.target.value }))}
            rows={3}
            className="w-full bg-black/40 border border-white/15 px-2 py-1 text-xs text-slate-200"
          />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <input
              placeholder="Scope"
              value={form.scope}
              onChange={(event) => setForm((prev) => ({ ...prev, scope: event.target.value }))}
              className="bg-black/40 border border-white/15 px-2 py-1 text-xs text-slate-200"
            />
            <input
              type="number"
              min={0}
              max={100}
              value={form.priority}
              onChange={(event) => setForm((prev) => ({ ...prev, priority: event.target.value }))}
              className="bg-black/40 border border-white/15 px-2 py-1 text-xs text-slate-200"
            />
            <select
              value={form.status}
              onChange={(event) => setForm((prev) => ({ ...prev, status: event.target.value }))}
              className="bg-black/40 border border-white/15 px-2 py-1 text-xs text-slate-200"
            >
              <option value="active">active</option>
              <option value="draft">draft</option>
              <option value="superseded">superseded</option>
            </select>
            <input
              placeholder="Tags (comma-separated)"
              value={form.tags}
              onChange={(event) => setForm((prev) => ({ ...prev, tags: event.target.value }))}
              className="bg-black/40 border border-white/15 px-2 py-1 text-xs text-slate-200"
            />
          </div>
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              className="text-[10px] px-3 py-1 border border-white/20 text-slate-300"
              onClick={() => {
                setForm(DEFAULT_FORM)
                setShowComposer(false)
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="text-[10px] px-3 py-1 border border-[#00e5ff]/40 text-[#00e5ff] hover:bg-[#00e5ff]/10 disabled:opacity-50"
            >
              {saving ? 'Saving...' : 'Save Directive'}
            </button>
          </div>
        </form>
      )}

      {error && (
        <div className="border border-rose-500/30 bg-rose-500/10 text-rose-200 text-[11px] px-2 py-2">
          {error}
        </div>
      )}
      {!canList && (
        <div className="border border-amber-400/30 bg-amber-400/10 text-amber-200 text-[11px] px-2 py-2">
          Running backend does not expose directives actions yet. Showing feed-only view.
        </div>
      )}

      <div className="space-y-2 max-h-64 min-h-[3rem] overflow-auto pr-1 [scrollbar-gutter:stable]">
        {loading && (
          <div className="text-[11px] text-slate-500 font-mono uppercase tracking-widest">Loading directives...</div>
        )}
        {!loading && items.length === 0 && (
          <div className="text-[11px] text-slate-500 font-mono tracking-wide border border-white/10 bg-black/30 px-2 py-2 rounded-sm">
            No directives found.
          </div>
        )}
        {!loading &&
          items.map((item) => (
            <div key={item.id} className="border border-white/10 bg-black/20 p-2">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-[11px] text-slate-200 uppercase tracking-wider truncate">{item.title || item.id}</div>
                  <div className="text-[10px] text-slate-500 font-mono mt-1 break-all">{item.id}</div>
                </div>
                <span className={`text-[9px] uppercase tracking-widest px-1.5 py-0.5 border ${statusTone(item.status)}`}>
                  {item.status}
                </span>
              </div>
              <MarkdownText content={item.body || 'No body'} size="xs" className="text-slate-300 mt-2" />
              <div className="flex items-center justify-between mt-2 text-[10px] text-slate-500 font-mono">
                <span>scope={item.scope || 'global'} priority={item.priority ?? 50}</span>
                {canArchive && String(item.status || '').toLowerCase() !== 'archived' && (
                  <button
                    type="button"
                    className="border border-rose-400/40 text-rose-300 px-2 py-0.5 hover:bg-rose-400/10 disabled:opacity-50"
                    disabled={saving}
                    onClick={() => archiveDirective(item.id)}
                  >
                    Archive
                  </button>
                )}
              </div>
            </div>
          ))}
      </div>
    </section>
  )
}
