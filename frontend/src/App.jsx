import { useState, useEffect, useCallback } from 'react'
import { FolderOpen, Layers, Wifi, WifiOff, CalendarClock } from 'lucide-react'
import { api } from './lib/api'
import { useWebSocket } from './hooks/useWebSocket'
import PlansPanel from './components/PlansPanel'
import WorkspaceView from './components/WorkspaceView'
import WorkspaceSwitcher from './components/WorkspaceSwitcher'
import PlanViewerModal from './components/PlanViewerModal'
import StatusSheet from './components/StatusSheet'

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
  const [statusOpen, setStatusOpen] = useState(false)
  const [statusTab, setStatusTab] = useState('schedule')
  const isMobile = useMobileBreakpoint()

  const [workspaces, setWorkspaces] = useState([])
  const [activeWorkspace, setActiveWorkspace] = useState(null)
  const [workspaceDetail, setWorkspaceDetail] = useState(null)
  const [scheduleStatus, setScheduleStatus] = useState(null)
  const [scheduleItems, setScheduleItems] = useState([])
  const [scheduleLoading, setScheduleLoading] = useState(false)
  const [scheduleError, setScheduleError] = useState('')

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
    }
  }, [])

  const loadSchedule = useCallback(async () => {
    setScheduleLoading(true)
    try {
      const [statusPayload, itemsPayload] = await Promise.all([api.getScheduleStatus(), api.getScheduleItems()])
      setScheduleStatus(statusPayload || null)
      setScheduleItems(Array.isArray(itemsPayload?.items) ? itemsPayload.items : [])
      setScheduleError('')
    } catch (error) {
      console.error('Failed to load schedule:', error)
      setScheduleError(error?.message || 'Failed to load schedule')
    } finally {
      setScheduleLoading(false)
    }
  }, [])

  const createScheduleItem = useCallback(
    async (payload) => {
      await api.upsertScheduleItem(payload)
      await loadSchedule()
    },
    [loadSchedule],
  )

  const closeScheduleItem = useCallback(
    async (itemId, payload = {}) => {
      await api.closeScheduleItem(itemId, payload)
      await loadSchedule()
    },
    [loadSchedule],
  )

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
    loadSchedule()
  }, [loadProject, loadWorkspaces, loadSchedule])

  useEffect(() => {
    const timer = window.setInterval(() => {
      loadSchedule()
    }, 5000)
    return () => window.clearInterval(timer)
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
      loadWorkspaces()
      if (data.slug && data.slug === activeWorkspace) {
        loadWorkspaceDetail(data.slug)
      }
    },
    onScheduleUpdated: () => {
      loadSchedule()
    },
  })

  const closeOverlays = useCallback(() => {
    setLeftOpen(false)
    setRightOpen(false)
    setStatusOpen(false)
  }, [])

  const toggleLeft = useCallback(() => {
    setLeftOpen((prev) => {
      const next = !prev
      if (next && isMobile) {
        setRightOpen(false)
        setStatusOpen(false)
      }
      return next
    })
  }, [isMobile])

  const toggleRight = useCallback(() => {
    setRightOpen((prev) => {
      const next = !prev
      if (next && isMobile) {
        setLeftOpen(false)
        setStatusOpen(false)
      }
      return next
    })
  }, [isMobile])

  const toggleStatus = useCallback(() => {
    setStatusOpen((prev) => {
      const next = !prev
      if (next && isMobile) {
        setLeftOpen(false)
        setRightOpen(false)
      }
      return next
    })
  }, [isMobile])

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

  const selectWorkspace = useCallback(
    (slug) => {
      setActiveWorkspace(slug)
      if (isMobile) setRightOpen(false)
    },
    [isMobile],
  )

  const anyOverlayOpen = leftOpen || rightOpen || statusOpen

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
        className={`fixed left-3 top-3 bottom-24 z-40 w-[min(22rem,calc(100vw-1.5rem))] rounded-2xl border border-slate-200 bg-white shadow-2xl transition-all duration-200 ${
          leftOpen ? 'translate-x-0 opacity-100 pointer-events-auto' : '-translate-x-[108%] opacity-0 pointer-events-none'
        }`}
      >
        <PlansPanel disciplines={disciplines} onPageClick={openPage} projectName={projectName} pageCount={pageCount} />
      </aside>

      <aside
        className={`fixed right-3 top-3 bottom-24 z-40 w-[min(24rem,calc(100vw-1.5rem))] rounded-2xl border border-slate-200 bg-white shadow-2xl transition-all duration-200 ${
          rightOpen ? 'translate-x-0 opacity-100 pointer-events-auto' : 'translate-x-[108%] opacity-0 pointer-events-none'
        }`}
      >
        <WorkspaceSwitcher workspaces={workspaces} activeSlug={activeWorkspace} onSelect={selectWorkspace} />
      </aside>

      <StatusSheet
        open={statusOpen}
        activeTab={statusTab}
        onTabChange={setStatusTab}
        onClose={() => setStatusOpen(false)}
        workspaceTitle={workspaceDetail?.title || workspaceDetail?.slug || ''}
        notes={workspaceDetail?.notes || []}
        scheduleStatus={scheduleStatus}
        scheduleItems={scheduleItems}
        scheduleLoading={scheduleLoading}
        scheduleError={scheduleError}
        onScheduleRefresh={loadSchedule}
        onScheduleCreate={createScheduleItem}
        onScheduleClose={closeScheduleItem}
      />

      <button
        type="button"
        onClick={toggleLeft}
        className={`fixed bottom-4 left-4 z-50 inline-flex items-center gap-2 rounded-full px-4 py-2.5 text-xs font-medium shadow-lg border transition-colors ${
          leftOpen ? 'bg-cyan-600 text-white border-cyan-600' : 'bg-white text-slate-700 border-slate-300 hover:bg-slate-50'
        }`}
        title="Toggle files panel"
      >
        <FolderOpen size={14} />
        Files
      </button>

      <button
        type="button"
        onClick={toggleStatus}
        className={`fixed bottom-4 left-1/2 -translate-x-1/2 z-50 inline-flex items-center gap-2 rounded-full px-4 py-2.5 text-xs font-medium shadow-lg border transition-colors ${
          statusOpen ? 'bg-amber-600 text-white border-amber-600' : 'bg-white text-slate-700 border-slate-300 hover:bg-slate-50'
        }`}
        title="Toggle AI status panel"
      >
        <CalendarClock size={14} />
        Status
      </button>

      <button
        type="button"
        onClick={toggleRight}
        className={`fixed bottom-4 right-4 z-50 inline-flex items-center gap-2 rounded-full px-4 py-2.5 text-xs font-medium shadow-lg border transition-colors ${
          rightOpen ? 'bg-emerald-600 text-white border-emerald-600' : 'bg-white text-slate-700 border-slate-300 hover:bg-slate-50'
        }`}
        title="Toggle workspaces panel"
      >
        <Layers size={14} />
        Workspaces
      </button>

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
