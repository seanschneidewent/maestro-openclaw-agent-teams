import { useCallback, useMemo, useState } from 'react'
import AddNodeTile from './components/AddNodeTile'
import DoctorPanel from './components/DoctorPanel'
import NodeIntelligenceModal from './components/NodeIntelligenceModal'
import ProjectNode from './components/ProjectNode'
import PurchaseCommandModal from './components/PurchaseCommandModal'
import SystemDirectivesPanel from './components/SystemDirectivesPanel'
import { api } from './lib/api'
import { useCommandCenterWebSocket } from './hooks/useCommandCenterWebSocket'
import useCommandCenterState from './hooks/useCommandCenterState'
import useProjectModalData from './hooks/useProjectModalData'

function SignalPulse() {
  return (
    <span className="relative flex h-2 w-2">
      <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 bg-[#00e5ff]" />
      <span className="relative inline-flex rounded-full h-2 w-2 bg-[#00e5ff]" />
    </span>
  )
}

function NetworkIcon() {
  return (
    <svg className="w-5 h-5 opacity-70" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.5}
        d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9"
      />
    </svg>
  )
}

export default function App() {
  const {
    state,
    setState,
    loadState,
    awareness,
    setAwareness,
    loadAwareness,
  } = useCommandCenterState()
  const {
    selectedProject,
    selectedDetail,
    selectedControl,
    loadingDetail,
    selectProject,
    refreshSelectedProject,
    clearSelection,
    syncSelectedProjectFromState,
  } = useProjectModalData()
  const [showPurchaseModal, setShowPurchaseModal] = useState(false)
  const [doctorRunning, setDoctorRunning] = useState(false)
  const [doctorReport, setDoctorReport] = useState(null)
  const [doctorError, setDoctorError] = useState('')

  useCommandCenterWebSocket({
    onInit: (payload) => {
      if (payload?.state) {
        setState(payload.state)
        syncSelectedProjectFromState(payload.state.projects || [])
      }
      if (payload?.awareness) setAwareness(payload.awareness)
    },
    onUpdated: (payload) => {
      if (payload?.state) {
        setState(payload.state)
        syncSelectedProjectFromState(payload.state.projects || [])
      }
      if (payload?.awareness) setAwareness(payload.awareness)
      if (selectedProject?.slug) {
        refreshSelectedProject(selectedProject.slug).catch(() => {})
      }
    },
  })

  const nextNodeBadge = awareness?.purchase?.next_node_badge || '+'

  const commanderNode = useMemo(
    () => ({
      slug: 'commander',
      is_commander: true,
      name: awareness?.commander?.display_name || state.orchestrator?.name || 'The Commander',
      node_display_name: awareness?.commander?.display_name || state.orchestrator?.name || 'The Commander',
      project_name: 'Command Center Control Plane',
      assignee: 'System Owner',
      agent_id: awareness?.commander?.agent_id || 'maestro-company',
      attention_score: 0,
      health: { variance_days: 0 },
      critical_path: { blocker_count: 0 },
      rfis: { open: 0 },
      agent_status: 'idle',
      current_task: state.orchestrator?.currentAction || 'Monitoring fleet telemetry',
      comms: awareness?.posture ? `System ${String(awareness.posture).toUpperCase()}` : 'Control plane online',
      last_updated: awareness?.generated_at || '',
      heartbeat: {
        available: true,
        is_fresh: true,
      },
      conversation_preview: {
        last_assistant_text: '',
      },
    }),
    [awareness?.commander?.agent_id, awareness?.commander?.display_name, awareness?.generated_at, awareness?.posture, state.orchestrator?.currentAction, state.orchestrator?.name],
  )

  const runDoctorFix = useCallback(async () => {
    setDoctorRunning(true)
    setDoctorError('')
    try {
      const payload = await api.runAction('doctor_fix', { fix: true, restart_gateway: true })
      if (payload?.doctor) setDoctorReport(payload.doctor)
      if (payload?.awareness) setAwareness(payload.awareness)
      await loadState()
    } catch (error) {
      const message = error?.message || 'Doctor action failed'
      if (message.includes('Unsupported action: doctor_fix')) {
        setDoctorError('This running Maestro server build does not expose doctor_fix yet. Run `maestro update` then restart `maestro up`.')
      } else {
        setDoctorError(message)
      }
    } finally {
      setDoctorRunning(false)
    }
  }, [loadState, setAwareness])

  return (
    <div className="min-h-screen bg-[#05080f] text-slate-300 font-sans p-4 md:p-6 lg:p-8 flex flex-col relative overflow-hidden selection:bg-[#00e5ff]/30">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(0,229,255,0.03)_0,transparent_100%)] pointer-events-none" />
      <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.02)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.02)_1px,transparent_1px)] bg-[size:4rem_4rem] [mask-image:radial-gradient(ellipse_60%_60%_at_50%_40%,#000_70%,transparent_100%)] pointer-events-none" />

      <header className="relative z-10 flex flex-col md:flex-row justify-between items-start md:items-end mb-10 pb-4 border-b border-white/10">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 bg-black/50 border border-white/20 flex items-center justify-center shadow-[inset_0_0_15px_rgba(255,255,255,0.05)]">
            <NetworkIcon />
          </div>
          <div>
            <h1 className="text-2xl font-light tracking-[0.4em] text-white uppercase leading-none">Command Center</h1>
            <p className="text-[#00e5ff] font-mono text-[10px] tracking-widest uppercase mt-2">Commander + Project Maestro Network</p>
          </div>
        </div>
        <div className="mt-4 md:mt-0 flex items-center gap-4 bg-black/40 border border-white/5 px-4 py-2">
          <div className="flex flex-col items-end">
            <span className="text-[9px] text-slate-500 font-mono uppercase tracking-widest mb-0.5">Commander Node</span>
            <span className="text-xs text-white uppercase tracking-wider">{commanderNode.node_display_name}</span>
          </div>
          <div className="h-8 w-px bg-white/10" />
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 bg-[#00e676] rounded-full shadow-[0_0_5px_#00e676]" />
            <span className="text-[10px] font-mono text-[#00e676] uppercase tracking-widest">Online</span>
          </div>
        </div>
      </header>

      <div className="flex-grow grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-12 relative z-10">
        <div className="lg:col-span-8 flex flex-col items-center">
          <button
            type="button"
            onClick={() => selectProject(commanderNode)}
            className="w-full max-w-md bg-[#0a0e17]/80 backdrop-blur-sm border border-[#00e5ff]/30 p-1 relative shadow-[0_0_30px_rgba(0,229,255,0.05)] text-left"
          >
            <div className="absolute top-0 left-0 w-2 h-2 border-t-2 border-l-2 border-[#00e5ff]" />
            <div className="absolute top-0 right-0 w-2 h-2 border-t-2 border-r-2 border-[#00e5ff]" />
            <div className="absolute bottom-0 left-0 w-2 h-2 border-b-2 border-l-2 border-[#00e5ff]" />
            <div className="absolute bottom-0 right-0 w-2 h-2 border-b-2 border-r-2 border-[#00e5ff]" />

            <div className="p-5 flex flex-col items-center">
              <div className="flex items-center gap-3 mb-3">
                <h2 className="text-lg font-medium tracking-[0.2em] text-white uppercase">{commanderNode.node_display_name}</h2>
                <span className="text-[9px] font-mono bg-[#00e5ff]/10 text-[#00e5ff] border border-[#00e5ff]/30 px-1.5 py-0.5 uppercase tracking-widest">
                  Tier 1
                </span>
              </div>
              <div className="flex items-center gap-2 mb-4">
                <SignalPulse />
                <span className="text-[#00e5ff] font-mono text-[10px] uppercase tracking-widest">{state.orchestrator?.status || 'Routing'}</span>
              </div>
              <div className="w-full bg-black/60 border border-white/5 p-3 text-xs text-slate-300 font-mono text-center">
                {state.orchestrator?.currentAction || 'Monitoring fleet telemetry'}
              </div>
            </div>
          </button>

          <div className="w-full flex flex-col items-center">
            <div className="w-px h-8 bg-gradient-to-b from-[#00e5ff] to-[#00e5ff]/40 shadow-[0_0_10px_#00e5ff]" />
            <div className="w-full max-w-[80%] xl:max-w-[75%] h-px bg-[#00e5ff]/40 relative flex justify-between">
              <div className="absolute left-0 -top-1 w-2 h-2 bg-[#05080f] border border-[#00e5ff] rounded-full" />
              <div className="absolute left-1/2 -ml-1 -top-1 w-2 h-2 bg-[#05080f] border border-[#00e5ff] rounded-full" />
              <div className="absolute right-0 -top-1 w-2 h-2 bg-[#05080f] border border-[#00e5ff] rounded-full" />
            </div>
          </div>

          <div className="w-full max-w-5xl grid grid-cols-1 md:grid-cols-3 gap-6 relative z-20">
            {(state.projects || []).map((project) => (
              <ProjectNode key={project.slug} project={project} onSelect={selectProject} />
            ))}
            <AddNodeTile badge={nextNodeBadge} onClick={() => setShowPurchaseModal(true)} />
            {(!state.projects || state.projects.length === 0) && (
              <div className="col-span-3 border border-white/10 bg-black/40 p-3 text-center text-slate-500 text-xs">
                No active project nodes yet. Use the add tile to provision the first project maestro.
              </div>
            )}
          </div>
        </div>

        <div className="lg:col-span-4 flex flex-col gap-6 relative">
          <DoctorPanel
            awareness={awareness}
            onRun={runDoctorFix}
            running={doctorRunning}
            report={doctorReport}
            error={doctorError}
          />

          <SystemDirectivesPanel
            availableActions={awareness?.available_actions || []}
            fallbackDirectives={state.directives || []}
            onChanged={async () => {
              await Promise.all([loadState(), loadAwareness()])
            }}
          />
        </div>
      </div>

      {selectedProject && (
        <NodeIntelligenceModal
          project={selectedProject}
          detail={selectedDetail}
          awareness={awareness}
          control={selectedControl}
          onClose={() => {
            clearSelection()
          }}
        />
      )}

      {selectedProject && loadingDetail && (
        <div className="fixed bottom-4 right-4 border border-[#00e5ff]/40 bg-black/70 px-3 py-2 text-xs font-mono text-[#00e5ff] z-50">
          Loading node intelligence...
        </div>
      )}

      {showPurchaseModal && (
        <PurchaseCommandModal
          awareness={awareness}
          onClose={() => setShowPurchaseModal(false)}
        />
      )}
    </div>
  )
}

