import { Layers, CheckCircle2, PanelRightClose, BookOpen } from 'lucide-react'

export default function WorkspaceSwitcher({ workspaces = [], activeSlug, onSelect, onCollapse }) {
  return (
    <div className="w-80 border-l border-slate-200 bg-gradient-to-b from-slate-50 to-white flex flex-col h-full">
      <div className="px-4 py-3 border-b border-slate-200 flex items-center justify-between bg-white/85 backdrop-blur-sm">
        <div className="flex items-center gap-2">
          {onCollapse && (
            <button onClick={onCollapse} className="p-1 hover:bg-slate-100 rounded" title="Collapse panel">
              <PanelRightClose size={14} className="text-slate-400" />
            </button>
          )}
          <Layers size={16} className="text-emerald-600" />
          <h2 className="text-sm font-semibold text-slate-800">Workspaces</h2>
        </div>
        <span className="text-xs text-slate-500">{workspaces.length}</span>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {workspaces.length === 0 ? (
          <div className="px-4 py-8 text-center text-slate-400 border border-dashed border-slate-300 rounded-xl bg-white">
            <Layers size={32} className="mx-auto mb-2 opacity-40" />
            <p className="text-xs">No workspaces yet</p>
            <p className="text-xs mt-1">Ask Maestro to create one</p>
          </div>
        ) : (
          workspaces.map(ws => {
            const isActive = ws.slug === activeSlug
            return (
              <button
                key={ws.slug}
                onClick={() => onSelect(ws.slug)}
                className={`w-full text-left p-3 transition-all rounded-xl border ${
                  isActive
                    ? 'bg-emerald-50 border-emerald-400 shadow-sm'
                    : 'bg-white border-slate-200 hover:border-slate-300'
                }`}
              >
                <div className="min-w-0 flex-1">
                  <p className={`text-sm font-semibold truncate ${isActive ? 'text-emerald-800' : 'text-slate-800'}`}>
                    {ws.title || ws.slug}
                  </p>
                  {ws.description && (
                    <p className="text-xs text-slate-500 mt-1 line-clamp-2">{ws.description}</p>
                  )}
                  <div className="flex items-center gap-3 mt-2 text-xs text-slate-500">
                    <span className="inline-flex items-center gap-1">
                      <BookOpen size={12} />
                      {ws.page_count || 0} pages
                    </span>
                    <span>{ws.note_count || 0} notes</span>
                  </div>
                </div>
              </button>
            )
          })
        )}
      </div>
    </div>
  )
}
