import { useEffect, useRef, useState } from 'react'

export function useCommandCenterWebSocket({ onInit, onUpdated }) {
  const [connected, setConnected] = useState(false)
  const wsRef = useRef(null)

  useEffect(() => {
    let active = true
    let retryTimer = null

    const connect = () => {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsUrl = `${protocol}//${window.location.host}/ws/command-center`
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        if (!active) return
        setConnected(true)
      }

      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data)
          if (payload.type === 'command_center_init' && onInit) {
            onInit(payload)
          }
          if (payload.type === 'command_center_updated' && onUpdated) {
            onUpdated(payload)
          }
        } catch (error) {
          console.error('Command center WS parse error', error)
        }
      }

      ws.onclose = () => {
        if (!active) return
        setConnected(false)
        retryTimer = window.setTimeout(connect, 1500)
      }

      ws.onerror = () => {
        ws.close()
      }
    }

    connect()

    return () => {
      active = false
      setConnected(false)
      if (retryTimer) window.clearTimeout(retryTimer)
      if (wsRef.current && wsRef.current.readyState < 2) {
        wsRef.current.close()
      }
    }
  }, [onInit, onUpdated])

  return { connected }
}
