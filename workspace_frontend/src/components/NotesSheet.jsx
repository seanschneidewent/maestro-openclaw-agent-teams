import { MessageSquare, Link2, NotebookPen } from 'lucide-react'
import MarkdownText from './MarkdownText'

const CATEGORY_STYLES = {
  slate: {
    badge: 'bg-slate-100 border-slate-300 text-slate-700',
    card: 'border-slate-200 bg-slate-50/50',
  },
  blue: {
    badge: 'bg-blue-100 border-blue-300 text-blue-700',
    card: 'border-blue-200 bg-blue-50/50',
  },
  green: {
    badge: 'bg-emerald-100 border-emerald-300 text-emerald-700',
    card: 'border-emerald-200 bg-emerald-50/50',
  },
  amber: {
    badge: 'bg-amber-100 border-amber-300 text-amber-700',
    card: 'border-amber-200 bg-amber-50/50',
  },
  red: {
    badge: 'bg-rose-100 border-rose-300 text-rose-700',
    card: 'border-rose-200 bg-rose-50/50',
  },
  purple: {
    badge: 'bg-fuchsia-100 border-fuchsia-300 text-fuchsia-700',
    card: 'border-fuchsia-200 bg-fuchsia-50/50',
  },
}

function getCategoryStyle(color) {
  return CATEGORY_STYLES[color] || CATEGORY_STYLES.slate
}

function normalizeSourcePages(note) {
  const sourcePages = Array.isArray(note?.source_pages) ? note.source_pages : []
  if (sourcePages.length > 0) {
    return sourcePages
      .map((item) => {
        if (typeof item === 'string') return { page_name: item, workspace_slug: '' }
        if (!item || typeof item !== 'object') return null
        const pageName = String(item.page_name || item.source_page || '').trim()
        if (!pageName) return null
        return {
          page_name: pageName,
          workspace_slug: String(item.workspace_slug || '').trim(),
        }
      })
      .filter(Boolean)
  }

  const legacy = String(note?.source_page || '').trim()
  return legacy ? [{ page_name: legacy, workspace_slug: '' }] : []
}

function sortCategories(categories = []) {
  return [...categories].sort((a, b) => {
    const orderA = Number.isFinite(Number(a?.order)) ? Number(a.order) : 0
    const orderB = Number.isFinite(Number(b?.order)) ? Number(b.order) : 0
    if (orderA !== orderB) return orderA - orderB
    return String(a?.name || '').localeCompare(String(b?.name || ''))
  })
}

function sortNotes(notes = []) {
  return [...notes].sort((a, b) => {
    const pinnedA = Boolean(a?.pinned)
    const pinnedB = Boolean(b?.pinned)
    if (pinnedA !== pinnedB) return pinnedA ? -1 : 1
    const updatedA = String(a?.updated_at || a?.created_at || '')
    const updatedB = String(b?.updated_at || b?.created_at || '')
    return updatedB.localeCompare(updatedA)
  })
}

function NoteCard({ note, category, onSourcePageClick }) {
  const style = getCategoryStyle(category?.color)
  const sourcePages = normalizeSourcePages(note)
  const isArchived = String(note?.status || '').toLowerCase() === 'archived'

  return (
    <div className={`border rounded-xl px-4 py-3 ${style.card} ${isArchived ? 'opacity-60' : ''}`}>
      <div className="flex items-start gap-2">
        <MessageSquare size={13} className="text-slate-500 mt-0.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <MarkdownText content={note.text} size="sm" className="text-slate-700" />
          <div className="mt-2 flex flex-wrap gap-1.5">
            {note.pinned ? (
              <span className="text-[11px] px-2 py-0.5 rounded-full border border-slate-300 bg-white text-slate-600">
                Pinned
              </span>
            ) : null}
            {isArchived ? (
              <span className="text-[11px] px-2 py-0.5 rounded-full border border-slate-300 bg-white text-slate-600">
                Archived
              </span>
            ) : null}
            {sourcePages.map((source, index) => (
              <button
                key={`${source.page_name}-${source.workspace_slug || 'global'}-${index}`}
                type="button"
                onClick={() => onSourcePageClick?.(source)}
                className="text-[11px] px-2 py-0.5 rounded-full border border-slate-300 bg-white text-slate-600 inline-flex items-center gap-1"
              >
                <Link2 size={11} />
                {source.workspace_slug ? `${source.workspace_slug} · ${source.page_name}` : source.page_name}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

export default function NotesSheet({ open, projectName, payload, onSourcePageClick }) {
  const categories = Array.isArray(payload?.categories) ? payload.categories : []
  const notes = Array.isArray(payload?.notes) ? payload.notes : []

  const categoryMap = new Map()
  for (const category of categories) {
    const id = String(category?.id || '').trim()
    if (!id) continue
    categoryMap.set(id, category)
  }
  if (!categoryMap.has('general')) {
    categoryMap.set('general', { id: 'general', name: 'General', color: 'slate', order: 0 })
  }

  const grouped = new Map()
  for (const note of notes) {
    const categoryId = String(note?.category_id || 'general').trim() || 'general'
    const list = grouped.get(categoryId) || []
    list.push(note)
    grouped.set(categoryId, list)
  }

  const orderedCategories = sortCategories([
    ...categoryMap.values(),
    ...[...grouped.keys()]
      .filter((id) => !categoryMap.has(id))
      .map((id) => ({ id, name: id.replaceAll('_', ' '), color: 'slate', order: 999 })),
  ])

  const hasNotes = notes.length > 0

  return (
    <section
      className={`fixed inset-x-2 top-3 bottom-20 z-40 rounded-2xl border border-slate-200 bg-white shadow-2xl transition-all duration-200 ${
        open ? 'translate-y-0 opacity-100 pointer-events-auto' : 'translate-y-[110%] opacity-0 pointer-events-none'
      }`}
      role="dialog"
      aria-modal="true"
      aria-label="Notes panel"
    >
      <div className="h-full overflow-auto p-4 bg-gradient-to-b from-slate-50 to-white rounded-2xl">
        <div className="bg-white rounded-xl border border-slate-200 p-4">
          <div className="flex items-center gap-2 mb-1">
            <NotebookPen size={14} className="text-slate-600" />
            <h3 className="text-sm font-semibold text-slate-800">Notes</h3>
          </div>
          <p className="text-xs text-slate-500 mb-3">{projectName || 'No active project'}</p>

          {!hasNotes ? (
            <p className="text-xs text-slate-400">No project notes yet.</p>
          ) : (
            <div className="space-y-4">
              {orderedCategories.map((category) => {
                const categoryId = String(category?.id || '')
                const categoryNotes = sortNotes(grouped.get(categoryId) || [])
                if (categoryNotes.length === 0) return null
                const style = getCategoryStyle(category?.color)
                return (
                  <div key={categoryId} className="space-y-2">
                    <div className="flex items-center justify-between">
                      <span className={`text-xs px-2 py-1 rounded-full border ${style.badge}`}>
                        {String(category?.name || categoryId)}
                      </span>
                      <span className="text-[11px] text-slate-500">{categoryNotes.length}</span>
                    </div>
                    <div className="space-y-2">
                      {categoryNotes.map((note) => (
                        <NoteCard
                          key={String(note?.id || `${categoryId}-${note?.text || ''}`)}
                          note={note}
                          category={category}
                          onSourcePageClick={onSourcePageClick}
                        />
                      ))}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
