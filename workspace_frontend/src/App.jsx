import { useState, useEffect, useCallback } from 'react'
import { FolderOpen, Layers, Wifi, WifiOff, CalendarClock, NotebookPen } from 'lucide-react'
import { api } from './lib/api'
import { useWebSocket } from './hooks/useWebSocket'
import PlansPanel from './components/PlansPanel'
import WorkspaceView from './components/WorkspaceView'
import WorkspaceSwitcher from './components/WorkspaceSwitcher'
import PlanViewerModal from './components/PlanViewerModal'
import ScheduleSheet from './components/ScheduleSheet'
import NotesSheet from './components/NotesSheet'

function currentMonthKey() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

function shiftMonthKey(monthKey, delta) {
  const [yearRaw, monthRaw] = String(monthKey || '').split('-')
  const year = Number(yearRaw)
  const month = Number(monthRaw)
  if (!Number.isInteger(year) || !Number.isInteger(month) || month < 1 || month > 12) {
    return currentMonthKey()
  }
  const next = new Date(year, month - 1 + delta, 1)
  return `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}`
}

function useMobileBreakpoint() {
  const [isMobile, setIsMobile] = useState(() => window.matchMedia('(max-width: 1023px)').matches)

  useEffect(() => {
    const query = window.matchMedia('(max-width: 1023px)')
    const update = () => setIsMobile(query.matches)
    update()
    if (query.addEventListener) {
      query.addEventListener('change', update)
      return () => query.removeEventListener('change', update)
    }
    query.addListener(update)
    return () => query.removeListener(update)
  }, [])

  return isMobile
}

export default function App() {
  const [projectName, setProjectName] = useState('')
  const [disciplines, setDisciplines] = useState([])
  const [pageCount, setPageCount] = useState(0)
  const [viewingPage, setViewingPage] = useState(null)
  const [leftOpen, setLeftOpen] = useState(false)
  const [rightOpen, setRightOpen] = useState(false)
  const [scheduleOpen, setScheduleOpen] = useState(false)
  const [notesOpen, setNotesOpen] = useState(false)
  const isMobile = useMobileBreakpoint()

  const [workspaces, setWorkspaces] = useState([])
  const [activeWorkspace, setActiveWorkspace] = useState(null)
  const [workspaceDetail, setWorkspaceDetail] = useState(null)
  const [scheduleTimeline, setScheduleTimeline] = useState(null)
  const [scheduleMonth, setScheduleMonth] = useState(() => currentMonthKey())
  const [scheduleLoading, setScheduleLoading] = useState(false)
  const [scheduleError, setScheduleError] = useState('')
  const [projectNotes, setProjectNotes] = useState({ categories: [], notes: [], updated_at: '' })

  const loadProject = useCallback(async () => {
    try {
      const data = await api.getProject()
      setProjectName(data.name || '')
      setDisciplines(data.disciplines || [])
      setPageCount(data.page_count || 0)
    } catch (error) {
      console.error('Failed to load project:', error)
    }
  }, [])

  const loadWorkspaces = useCallback(async () => {
    try {
      const data = await api.getWorkspaces()
      const list = data.workspaces || []
      setWorkspaces(list)
      return list
    } catch (error) {
      console.error('Failed to load workspaces:', error)
      return []
    }
  }, [])

  const loadWorkspaceDetail = useCallback(async (slug) => {
    if (!slug) {
      setWorkspaceDetail(null)
      return
    }
    try {
      const data = await api.getWorkspace(slug)
      setWorkspaceDetail(data)
    } catch (error) {
      console.error('Failed to load workspace:', error)
      setWorkspaceDetail(null)
    }
  }, [])

  const syncWorkspaceAfterEvent = useCallback(async (eventSlug) => {
    const list = await loadWorkspaces()
    const activeExists = Boolean(activeWorkspace && list.some((ws) => ws.slug === activeWorkspace))

    if (!activeExists) {
      const nextSlug = list.length > 0 ? list[0].slug : null
      if (nextSlug !== activeWorkspace) {
        setActiveWorkspace(nextSlug)
      }
      if (!nextSlug) {
        setWorkspaceDetail(null)
      }
      return
    }

    if (eventSlug) {
      const cleanSlug = String(eventSlug)
      if (cleanSlug === activeWorkspace) {
        await loadWorkspaceDetail(cleanSlug)
      }
      return
    }

    if (activeWorkspace) {
      await loadWorkspaceDetail(activeWorkspace)
    }
  }, [activeWorkspace, loadWorkspaces, loadWorkspaceDetail])

  const loadSchedule = useCallback(async (options = {}) => {
    const silent = Boolean(options?.silent)
    if (!silent) setScheduleLoading(true)
    try {
      const timelinePayload = await api.getScheduleTimeline({
        month: scheduleMonth,
        includeEmptyDays: true,
      })
      setScheduleTimeline(timelinePayload || null)
      setScheduleError('')
    } catch (error) {
      console.error('Failed to load schedule:', error)
      setScheduleError(error?.message || 'Failed to load schedule')
    } finally {
      if (!silent) setScheduleLoading(false)
    }
  }, [scheduleMonth])

  const loadProjectNotes = useCallback(async () => {
    try {
      const payload = await api.getProjectNotes()
      setProjectNotes({
        categories: Array.isArray(payload?.categories) ? payload.categories : [],
        notes: Array.isArray(payload?.notes) ? payload.notes : [],
        updated_at: payload?.updated_at || '',
      })
    } catch (error) {
      console.error('Failed to load project notes:', error)
      setProjectNotes({ categories: [], notes: [], updated_at: '' })
    }
  }, [])

  useEffect(() => {
    loadProject()
    loadWorkspaces().then((list) => {
      const params = new URLSearchParams(window.location.search)
      const wsSlug = params.get('workspace')
      if (wsSlug) {
        setActiveWorkspace(wsSlug)
      } else if (list.length > 0) {
        setActiveWorkspace((prev) => prev || list[0].slug)
      }
    })
    loadProjectNotes()
  }, [loadProject, loadWorkspaces, loadProjectNotes])

  useEffect(() => {
    loadSchedule()
  }, [loadSchedule])

  useEffect(() => {
    loadWorkspaceDetail(activeWorkspace)
  }, [activeWorkspace, loadWorkspaceDetail])

  const { connected } = useWebSocket({
    onInit: (data) => {
      setDisciplines(data.disciplines || [])
      setPageCount(data.page_count || 0)
    },
    onPageAdded: () => loadProject(),
    onPageUpdated: () => loadProject(),
    onRegionComplete: () => loadProject(),
    onWorkspaceUpdated: (data) => {
      syncWorkspaceAfterEvent(data?.slug)
    },
    onScheduleUpdated: () => {
      loadSchedule({ silent: true })
    },
    onProjectNotesUpdated: () => {
      loadProjectNotes()
    },
    onReload: () => {
      loadProject()
      syncWorkspaceAfterEvent()
      loadSchedule({ silent: true })
      loadProjectNotes()
    },
  })

  useEffect(() => {
    if (connected) return undefined
    const timer = window.setInterval(() => {
      loadSchedule({ silent: true })
      loadProjectNotes()
    }, 30000)
    return () => window.clearInterval(timer)
  }, [connected, loadSchedule, loadProjectNotes])

  const closeOverlays = useCallback(() => {
    setLeftOpen(false)
    setRightOpen(false)
    setScheduleOpen(false)
    setNotesOpen(false)
  }, [])

  const toggleLeft = useCallback(() => {
    setLeftOpen((prev) => {
      const next = !prev
      if (next) {
        setRightOpen(false)
        setScheduleOpen(false)
        setNotesOpen(false)
      }
      return next
    })
  }, [])

  const toggleRight = useCallback(() => {
    setRightOpen((prev) => {
      const next = !prev
      if (next) {
        setLeftOpen(false)
        setScheduleOpen(false)
        setNotesOpen(false)
      }
      return next
    })
  }, [])

  const toggleSchedule = useCallback(() => {
    setScheduleOpen((prev) => {
      const next = !prev
      if (next) {
        setNotesOpen(false)
        setLeftOpen(false)
        setRightOpen(false)
      }
      return next
    })
  }, [])

  const toggleNotes = useCallback(() => {
    setNotesOpen((prev) => {
      const next = !prev
      if (next) {
        setScheduleOpen(false)
        setLeftOpen(false)
        setRightOpen(false)
      }
      return next
    })
  }, [])

  const openPage = useCallback(
    (pageName, selectedPointers, customHighlights) => {
      setViewingPage({
        pageName,
        title: pageName,
        imageUrl: api.getPageImageUrl(pageName),
        selectedPointers: selectedPointers || null,
        customHighlights: customHighlights || [],
      })
      if (isMobile) setLeftOpen(false)
    },
    [isMobile],
  )

  const openGeneratedImage = useCallback((imageUrl, imageData) => {
    setViewingPage({
      pageName: imageData.filename,
      title: imageData.prompt || 'Generated Image',
      imageUrl,
      selectedPointers: null,
      customHighlights: [],
    })
  }, [])

  const openNoteSourcePage = useCallback(async (source) => {
    const pageName = String(source?.page_name || '').trim()
    if (!pageName) return

    const fallbackWorkspace = activeWorkspace || (workspaces.length > 0 ? String(workspaces[0]?.slug || '') : '')
    const sourceWorkspace = String(source?.workspace_slug || '').trim()
    const targetWorkspace = sourceWorkspace || fallbackWorkspace

    let selectedPointers = null
    let customHighlights = []

    if (targetWorkspace) {
      try {
        const data = await api.getWorkspace(targetWorkspace)
        const pages = Array.isArray(data?.pages) ? data.pages : []
        const pageEntry = pages.find((entry) => String(entry?.page_name || '').trim() === pageName)
        if (pageEntry) {
          selectedPointers = Array.isArray(pageEntry.selected_pointers) ? pageEntry.selected_pointers : null
          customHighlights = Array.isArray(pageEntry.custom_highlights) ? pageEntry.custom_highlights : []
        }
      } catch (error) {
        console.error('Failed to open note source workspace page:', error)
      }
    }

    if (targetWorkspace && targetWorkspace !== activeWorkspace) {
      setActiveWorkspace(targetWorkspace)
    }

    setViewingPage({
      pageName,
      title: pageName,
      imageUrl: api.getPageImageUrl(pageName),
      selectedPointers,
      customHighlights,
    })
    setNotesOpen(false)
  }, [activeWorkspace, workspaces])

  const selectWorkspace = useCallback(
    (slug) => {
      setActiveWorkspace(slug)
      if (isMobile) setRightOpen(false)
    },
    [isMobile],
  )

  const anyOverlayOpen = leftOpen || rightOpen || scheduleOpen || notesOpen

  useEffect(() => {
    if (!anyOverlayOpen) return undefined
    const onKeyDown = (event) => {
      if (event.key === 'Escape') closeOverlays()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [anyOverlayOpen, closeOverlays])

  useEffect(() => {
    if (!anyOverlayOpen) return undefined
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previousOverflow
    }
  }, [anyOverlayOpen])

  return (
    <div className="h-screen bg-white text-slate-800 overflow-hidden relative">
      <div className="h-full flex flex-col">
        <WorkspaceView
          workspace={workspaceDetail}
          onPageClick={openPage}
          onImageClick={openGeneratedImage}
        />

        <div className="absolute top-3 right-3 z-20 inline-flex items-center gap-1.5 text-xs text-slate-500 bg-white/90 border border-slate-200 rounded-full px-2.5 py-1 shadow-sm">
          {connected ? (
            <>
              <Wifi size={12} className="text-emerald-500" />
              <span>Live</span>
            </>
          ) : (
            <>
              <WifiOff size={12} className="text-slate-400" />
              <span>Connecting...</span>
            </>
          )}
        </div>
      </div>

      {anyOverlayOpen && (
        <button
          type="button"
          aria-label="Close panels"
          className="fixed inset-0 z-30 bg-slate-900/20 backdrop-blur-[1px]"
          onClick={closeOverlays}
        />
      )}

      <aside
        className={`fixed left-3 top-3 bottom-24 z-40 w-[min(22rem,calc(100vw-1.5rem))] rounded-2xl border border-slate-200 bg-white shadow-2xl overflow-hidden transition-all duration-200 ${
          leftOpen ? 'translate-x-0 opacity-100 pointer-events-auto' : '-translate-x-[108%] opacity-0 pointer-events-none'
        }`}
      >
        <PlansPanel disciplines={disciplines} onPageClick={openPage} projectName={projectName} pageCount={pageCount} />
      </aside>

      <aside
        className={`fixed right-3 top-3 bottom-24 z-40 w-[min(24rem,calc(100vw-1.5rem))] rounded-2xl border border-slate-200 bg-white shadow-2xl overflow-hidden transition-all duration-200 ${
          rightOpen ? 'translate-x-0 opacity-100 pointer-events-auto' : 'translate-x-[108%] opacity-0 pointer-events-none'
        }`}
      >
        <WorkspaceSwitcher workspaces={workspaces} activeSlug={activeWorkspace} onSelect={selectWorkspace} />
      </aside>

      <ScheduleSheet
        open={scheduleOpen}
        scheduleTimeline={scheduleTimeline}
        scheduleMonth={scheduleMonth}
        scheduleLoading={scheduleLoading}
        scheduleError={scheduleError}
        onScheduleRefresh={loadSchedule}
        onScheduleMonthPrev={() => setScheduleMonth((prev) => shiftMonthKey(prev, -1))}
        onScheduleMonthNext={() => setScheduleMonth((prev) => shiftMonthKey(prev, 1))}
        onScheduleMonthToday={() => setScheduleMonth(currentMonthKey())}
      />

      <NotesSheet
        open={notesOpen}
        projectName={projectName}
        payload={projectNotes}
        onSourcePageClick={openNoteSourcePage}
      />

      <nav className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 inline-flex items-center gap-2 rounded-full border border-slate-300 bg-white/95 backdrop-blur-sm p-1.5 shadow-xl">
        <button
          type="button"
          onClick={toggleLeft}
          className={`h-10 w-10 inline-flex items-center justify-center rounded-full border transition-colors ${
            leftOpen ? 'bg-cyan-600 text-white border-cyan-600' : 'bg-white text-slate-700 border-slate-300 hover:bg-slate-50'
          }`}
          title="Files"
          aria-label="Files"
        >
          <FolderOpen size={16} />
        </button>
        <button
          type="button"
          onClick={toggleSchedule}
          className={`h-10 w-10 inline-flex items-center justify-center rounded-full border transition-colors ${
            scheduleOpen ? 'bg-amber-600 text-white border-amber-600' : 'bg-white text-slate-700 border-slate-300 hover:bg-slate-50'
          }`}
          title="Schedule"
          aria-label="Schedule"
        >
          <CalendarClock size={16} />
        </button>
        <button
          type="button"
          onClick={toggleNotes}
          className={`h-10 w-10 inline-flex items-center justify-center rounded-full border transition-colors ${
            notesOpen ? 'bg-orange-600 text-white border-orange-600' : 'bg-white text-slate-700 border-slate-300 hover:bg-slate-50'
          }`}
          title="Notes"
          aria-label="Notes"
        >
          <NotebookPen size={16} />
        </button>
        <button
          type="button"
          onClick={toggleRight}
          className={`h-10 w-10 inline-flex items-center justify-center rounded-full border transition-colors ${
            rightOpen ? 'bg-emerald-600 text-white border-emerald-600' : 'bg-white text-slate-700 border-slate-300 hover:bg-slate-50'
          }`}
          title="Workspaces"
          aria-label="Workspaces"
        >
          <Layers size={16} />
        </button>
      </nav>

      {viewingPage && (
        <PlanViewerModal
          pageName={viewingPage.pageName}
          title={viewingPage.title}
          imageUrl={viewingPage.imageUrl}
          selectedPointers={viewingPage.selectedPointers}
          customHighlights={viewingPage.customHighlights}
          onClose={() => setViewingPage(null)}
        />
      )}
    </div>
  )
}
