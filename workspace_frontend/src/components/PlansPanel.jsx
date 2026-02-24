import { useState } from 'react'
import { ChevronRight, FileText, FolderOpen, PanelLeftClose } from 'lucide-react'
import { api } from '../lib/api'

const DISCIPLINE_LABELS = {
  architectural: 'Architectural',
  structural: 'Structural',
  mep: 'MEP',
  mechanical: 'Mechanical',
  electrical: 'Electrical',
  plumbing: 'Plumbing',
  civil: 'Civil',
  kitchen: 'Kitchen',
  landscape: 'Landscape',
  vapor_mitigation: 'Vapor Mitigation',
  canopy: 'Canopy',
  general: 'General',
  unknown: 'Unknown',
}

function disciplineLabel(code) {
  return DISCIPLINE_LABELS[code?.toLowerCase()] || code || 'Unknown'
}

export default function PlansPanel({
  disciplines,
  onPageClick,
  onCollapse,
  projectName,
  pageCount,
}) {
  const [expanded, setExpanded] = useState({})
  const [pages, setPages] = useState({})

  const toggle = async (disc) => {
    const key = disc
    const isOpen = expanded[key]
    setExpanded((prev) => ({ ...prev, [key]: !isOpen }))

    if (!isOpen && !pages[key]) {
      try {
        const res = await api.getPages(disc)
        setPages((prev) => ({ ...prev, [key]: res.pages || [] }))
      } catch (error) {
        console.error(error)
      }
    }
  }

  return (
    <>
      <div className="px-4 py-3 border-b border-slate-200 flex items-start justify-between gap-2">
        <div>
          <h1 className="text-lg font-bold">
            Maestro<span className="text-cyan-600">Plans</span>
          </h1>
          <p className="text-xs text-slate-400 mt-0.5 truncate max-w-44">
            {projectName || 'No project loaded'}
          </p>
          {pageCount > 0 && (
            <p className="text-xs text-slate-500 mt-0.5">{pageCount} pages</p>
          )}
        </div>
        {onCollapse && (
          <button
            onClick={onCollapse}
            className="p-1 hover:bg-slate-100 rounded mt-0.5"
            title="Collapse panel"
          >
            <PanelLeftClose size={14} className="text-slate-400" />
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto">
        {(disciplines || []).map((disc) => {
          const isOpen = expanded[disc]
          const discPages = pages[disc] || []

          return (
            <div key={disc}>
              <button
                onClick={() => toggle(disc)}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-slate-50 text-left"
              >
                <ChevronRight
                  size={14}
                  className={`shrink-0 text-slate-400 transition-transform ${isOpen ? 'rotate-90' : ''}`}
                />
                <FolderOpen size={14} className="shrink-0 text-cyan-600" />
                <span className="truncate font-medium">{disciplineLabel(disc)}</span>
              </button>

              {isOpen && (
                <div className="pl-5">
                  {discPages.map((page) => (
                    <button
                      key={page.name}
                      onClick={() => onPageClick(page.name)}
                      className="w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-cyan-50 text-left rounded-r"
                    >
                      <FileText size={12} className="shrink-0 text-slate-400" />
                      <span className="truncate">{page.name}</span>
                      <span className="ml-auto text-[10px] text-slate-400">
                        {page.region_count || 0}r
                      </span>
                    </button>
                  ))}
                  {discPages.length === 0 && (
                    <p className="px-3 py-1.5 text-xs text-slate-400">Loading...</p>
                  )}
                </div>
              )}
            </div>
          )
        })}
        {(!disciplines || disciplines.length === 0) && (
          <p className="px-4 py-8 text-sm text-slate-400 text-center">
            No plans loaded yet
          </p>
        )}
      </div>
    </>
  )
}
