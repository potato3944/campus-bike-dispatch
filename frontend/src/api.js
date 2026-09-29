// 后端 REST API 封装
const BASE = ''

async function request(path, options = {}) {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) throw new Error(`API ${path} -> ${res.status}`)
  return res.json()
}

export const api = {
  health: () => request('/api/health'),
  config: () => request('/api/config'),
  hotspots: () => request('/api/hotspots'),
  bikes: (limit = 3000) => request(`/api/bikes?limit=${limit}`),
  scanClusters: () => request('/api/clusters/scan', { method: 'POST' }),
  getClusters: () => request('/api/clusters'),
  dispatch: () => request('/api/dispatch', { method: 'POST' }),
  simulation: (strategy) =>
    request('/api/simulation', {
      method: 'POST',
      body: JSON.stringify(strategy ? { strategy } : {}),
    }),
  evolution: (steps = 60, bikes = 350) =>
    request(`/api/evolution?steps=${steps}&bikes=${bikes}`),
  scenarios: () => request('/api/scenarios'),
  scenarioData: (id, bikes = 350, steps = 60) =>
    request(`/api/scenario/${id}?bikes=${bikes}&steps=${steps}`),
}

export function connectGpsWs(onMessage, onError) {
  // WebSocket 实时 GPS 数据通道（Vite 代理 /ws -> 后端）
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const ws = new WebSocket(`${proto}://${location.host}/ws/gps`)
  ws.onmessage = (e) => {
    try {
      onMessage(JSON.parse(e.data))
    } catch (err) {
      console.warn('ws parse error', err)
    }
  }
  ws.onerror = (e) => onError && onError(e)
  return ws
}
