import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'

const DEFAULT_STATE = {
  commander: { name: 'The Commander', lastSeen: 'Unknown' },
  orchestrator: { id: 'CM-01', name: 'The Commander', status: 'Idle', currentAction: 'Awaiting telemetry' },
  directives: [],
  projects: [],
}

export default function useCommandCenterState() {
  const [state, setState] = useState(DEFAULT_STATE)
  const [awareness, setAwareness] = useState(null)

  const loadState = useCallback(async () => {
    try {
      const payload = await api.getState()
      setState(payload)
    } catch (error) {
      console.error('Failed to load command center state', error)
    }
  }, [])

  const loadAwareness = useCallback(async () => {
    try {
      const payload = await api.getAwareness()
      setAwareness(payload)
    } catch (error) {
      console.error('Failed to load awareness state', error)
    }
  }, [])

  useEffect(() => {
    loadState()
    loadAwareness()
  }, [loadState, loadAwareness])

  return {
    state,
    setState,
    loadState,
    awareness,
    setAwareness,
    loadAwareness,
  }
}
