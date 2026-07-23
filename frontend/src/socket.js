export function createRingSocket({ url, onEvent, onStatus }) {
  let socket = null
  let reconnectTimer = null
  let retryCount = 0
  let manuallyClosed = false

  function setStatus(status, detail = '') {
    onStatus?.({ status, detail })
  }

  function scheduleReconnect() {
    if (manuallyClosed || reconnectTimer) return
    const delay = Math.min(1000 * 2 ** retryCount, 10_000)
    retryCount += 1
    setStatus('reconnecting', `Retrying in ${Math.round(delay / 1000)}s`)
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null
      connect()
    }, delay)
  }

  function connect({ manual = false } = {}) {
    if (manual) {
      manuallyClosed = false
      retryCount = 0
    }
    if (reconnectTimer) {
      window.clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (socket?.readyState === WebSocket.OPEN || socket?.readyState === WebSocket.CONNECTING) {
      socket.close()
    }

    setStatus('connecting')
    let current
    try {
      current = new WebSocket(url)
      socket = current
    } catch (error) {
      setStatus('offline', error.message)
      scheduleReconnect()
      return
    }

    current.addEventListener('open', () => {
      if (socket !== current) return
      retryCount = 0
      setStatus('online')
    })
    current.addEventListener('message', (message) => {
      if (socket !== current) return
      try {
        const parsed = JSON.parse(message.data)
        if (!parsed || typeof parsed.type !== 'string' || !parsed.payload || typeof parsed.payload !== 'object' || Array.isArray(parsed.payload)) {
          throw new Error('Unexpected event shape')
        }
        onEvent?.(parsed)
      } catch (error) {
        onEvent?.({
          type: 'error',
          timestamp: Date.now(),
          payload: { code: 'MALFORMED_WS_EVENT', message: error.message },
        })
      }
    })
    current.addEventListener('error', () => {
      if (socket === current) setStatus('offline', 'Connection error')
    })
    current.addEventListener('close', () => {
      if (socket !== current) return
      setStatus('offline')
      scheduleReconnect()
    })
  }

  function close() {
    manuallyClosed = true
    if (reconnectTimer) window.clearTimeout(reconnectTimer)
    reconnectTimer = null
    socket?.close()
  }

  return { connect, close }
}
