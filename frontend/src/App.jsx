import { useState, useEffect, useCallback } from 'react'
import { FolderOpen, Layers, Wifi, WifiOff } from 'lucide-react'
import { api } from './lib/api'
import { useWebSocket } from './hooks/useWebSocket'
import PlansPanel from './components/PlansPanel'
import WorkspaceView from './components/WorkspaceView'
import WorkspaceSwitcher from './components/WorkspaceSwitcher'
import PlanViewerModal from './components/PlanViewerModal'

export default function App() {
  const [projectName, setProjectName] = useState('')
  const [disciplines, setDisciplines] = useState([])
  const [pageCount, setPageCount] = useState(0)
  const [viewingPage, setViewingPage] = useState(null)
  const [leftCollapsed, setLeftCollapsed] = useState(false)
  const [rightCollapsed, setRightCollapsed] = useState(false)

  // Workspaces
  const [workspaces, setWorkspaces] = useState([])
  const [activeWorkspace, setActiveWorkspace] = useState(null)
  const [workspaceDetail, setWorkspaceDetail] = useState(null)

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
      setWorkspaces(data.workspaces || [])
    } catch (error) {
      console.error('Failed to load workspaces:', error)
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

  useEffect(() => {
    loadProject()
    loadWorkspaces().then(() => {
      // Deep link: ?workspace=slug auto-selects workspace
      const params = new URLSearchParams(window.location.search)
      const wsSlug = params.get('workspace')
      if (wsSlug) setActiveWorkspace(wsSlug)
    })
  }, [loadProject, loadWorkspaces])

  useEffect(() => {
    loadWorkspaceDetail(activeWorkspace)
  }, [activeWorkspace, loadWorkspaceDetail])

  // Live updates
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
      // Reload detail if it's the active workspace
      if (data.slug && data.slug === activeWorkspace) {
        loadWorkspaceDetail(data.slug)
      }
    },
  })

  const openPage = useCallback((pageName, selectedPointers, customHighlights) => {
    setViewingPage({
      pageName,
      title: pageName,
      imageUrl: api.getPageImageUrl(pageName),
      selectedPointers: selectedPointers || null,
      customHighlights: customHighlights || [],
    })
  }, [])

  const openGeneratedImage = useCallback((imageUrl, imageData) => {
    setViewingPage({
      pageName: imageData.filename,
      title: imageData.prompt || 'Generated Image',
      imageUrl,
      selectedPointers: null,
      customHighlights: [],
    })
  }, [])

  return (
    <div className="h-screen flex bg-white text-slate-800 overflow-hidden">
      {/* Left: Plans Tree */}
      <div
        className={`shrink-0 border-r border-slate-200 flex flex-col overflow-hidden transition-all duration-200 ${
          leftCollapsed ? 'w-12' : 'w-60'
        }`}
      >
        {leftCollapsed ? (
          <button
            onClick={() => setLeftCollapsed(false)}
            className="flex items-center justify-center py-4 hover:bg-slate-50"
            title="Expand plans"
          >
            <FolderOpen size={18} className="text-cyan-600" />
          </button>
        ) : (
          <PlansPanel
            disciplines={disciplines}
            onPageClick={openPage}
            onCollapse={() => setLeftCollapsed(true)}
            projectName={projectName}
            pageCount={pageCount}
          />
        )}
      </div>

      {/* Center: Workspace */}
      <div className="flex-1 overflow-hidden flex flex-col relative">
        <WorkspaceView
          workspace={workspaceDetail}
          onPageClick={openPage}
          onImageClick={openGeneratedImage}
        />

        {/* Connection indicator */}
        <div className="absolute bottom-3 right-3 flex items-center gap-1.5 text-xs text-slate-400">
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

      {/* Right: Workspaces */}
      <div
        className={`shrink-0 border-l border-slate-200 flex flex-col overflow-hidden transition-all duration-200 ${
          rightCollapsed ? 'w-12' : 'w-80'
        }`}
      >
        {rightCollapsed ? (
          <button
            onClick={() => setRightCollapsed(false)}
            className="flex items-center justify-center py-4 hover:bg-slate-50"
            title="Expand workspaces"
          >
            <Layers size={18} className="text-cyan-600" />
          </button>
        ) : (
          <WorkspaceSwitcher
            workspaces={workspaces}
            activeSlug={activeWorkspace}
            onSelect={setActiveWorkspace}
            onCollapse={() => setRightCollapsed(true)}
          />
        )}
      </div>

      {/* Plan Viewer Modal */}
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
