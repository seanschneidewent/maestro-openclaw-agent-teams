import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'

export function useWebSocket({ onPageAdded, onPageUpdated, onRegionComplete, onInit, onWorkspaceUpdated } = {}) {
  const wsRef = useRef(null)
  const [connected, setConnected] = useState(false)
  const handlersRef = useRef({ onPageAdded, onPageUpdated, onRegionComplete, onInit, onWorkspaceUpdated })

  useEffect(() => {
    handlersRef.current = { onPageAdded, onPageUpdated, onRegionComplete, onInit, onWorkspaceUpdated }
  }, [onPageAdded, onPageUpdated, onRegionComplete, onInit, onWorkspaceUpdated])

  useEffect(() => {
    const url = api.getWsUrl()
    let ws
    let retryTimeout

    function connect() {
      ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => setConnected(true)

      ws.onmessage = (evt) => {
        try {
          const data = JSON.parse(evt.data)
          const h = handlersRef.current
          if (data.type === 'init' && h.onInit) h.onInit(data)
          if (data.type === 'page_added' && h.onPageAdded) h.onPageAdded(data)
          if (data.type === 'page_updated' && h.onPageUpdated) h.onPageUpdated(data)
          if (data.type === 'page_image_ready' && h.onPageUpdated) h.onPageUpdated(data)
          if (data.type === 'region_complete' && h.onRegionComplete) h.onRegionComplete(data)
          if (data.type === 'workspace_updated' && h.onWorkspaceUpdated) h.onWorkspaceUpdated(data)
        } catch (error) {
          console.error('Invalid WebSocket event', error)
        }
      }

      ws.onclose = () => {
        setConnected(false)
        retryTimeout = setTimeout(connect, 3000)
      }

      ws.onerror = () => ws.close()
    }

    connect()
    return () => {
      clearTimeout(retryTimeout)
      if (wsRef.current) wsRef.current.close()
    }
  }, [])

  return { wsRef, connected }
}
