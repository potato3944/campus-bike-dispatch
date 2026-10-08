<template>
  <div class="map-view">
    <div ref="mapEl" class="map-container"></div>

    <!-- 极简设计图例 (Dieter Rams / Swiss Style) -->
    <div v-if="mapReady" class="minimal-legend">
      <div class="legend-row">
        <span class="legend-item"><i class="badge-dot dot-surge"></i>严重堆积 (Lv.3)</span>
        <span class="legend-item"><i class="badge-dot dot-mid"></i>轻中度堆积</span>
        <span class="legend-item"><i class="badge-dot dot-shortage"></i>车辆空缺</span>
        <span class="legend-item"><i class="badge-dot dot-idle"></i>停放点</span>
        <span class="legend-item"><i class="badge-dot dot-moving"></i>骑行流动</span>
        <span class="legend-item"><i class="badge-dot dot-truck"></i>调度专车</span>
      </div>
    </div>

    <!-- 右上角极简图层切换 -->
    <div v-if="mapReady" class="minimal-layer-controls">
      <button class="layer-pill" :class="{ active: showHeat }" @click="$emit('toggle-layer', 'heat')">
        热力分布
      </button>
      <button class="layer-pill" :class="{ active: showClusters }" @click="$emit('toggle-layer', 'clusters')">
        聚类圈
      </button>
      <button class="layer-pill" :class="{ active: showBikes }" @click="$emit('toggle-layer', 'bikes')">
        车辆粒子
      </button>
      <button class="layer-pill" :class="{ active: showTrucks }" @click="$emit('toggle-layer', 'trucks')">
        调度路线
      </button>
    </div>

    <div v-if="!mapReady" class="map-loading">
      <div class="loading-ring"></div>
      <span class="loading-text">正在加载校园底图…</span>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import 'leaflet.heat'

const props = defineProps({
  config: Object,
  hotspots: Array,
  bikes: Array,
  clusters: Array,
  shortages: Array,
  heat: Array,
  trucks: Array,
  dispatch: Object,
  showHeat: { type: Boolean, default: true },
  showClusters: { type: Boolean, default: true },
  showBikes: { type: Boolean, default: true },
  showTrucks: { type: Boolean, default: true },
  showHotspots: { type: Boolean, default: true },
})

defineEmits(['toggle-layer'])

const mapEl = ref(null)
const mapReady = ref(false)
let map = null
let heatLayer = null
let bikeCanvasLayer = null
let clusterMarkers = []
let shortageMarkers = []
let truckMarkers = []
let routeLayers = []
let hotspotMarkers = []

/* =========================================================================
   极简高质感 Canvas 粒子流引擎 (无眩光、精细点位、方向矢量)
   ========================================================================= */
function createBikeCanvasLayer(mapInstance) {
  const canvas = document.createElement('canvas')
  Object.assign(canvas.style, {
    position: 'absolute',
    left: '0',
    top: '0',
    pointerEvents: 'none',
    zIndex: '450',
  })
  mapInstance.getContainer().appendChild(canvas)
  const ctx = canvas.getContext('2d', { alpha: true })

  let currentPoints = []
  let targetPoints = []
  let animId = null
  let isVisible = true

  function resize() {
    const dpr = window.devicePixelRatio || 1
    const size = mapInstance.getSize()
    if (!size || size.x === 0 || size.y === 0) return
    canvas.width = Math.round(size.x * dpr)
    canvas.height = Math.round(size.y * dpr)
    canvas.style.width = size.x + 'px'
    canvas.style.height = size.y + 'px'
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  }

  function renderFrame() {
    const size = mapInstance.getSize()
    ctx.clearRect(0, 0, size.x, size.y)
    if (!isVisible || !currentPoints.length) return

    for (let i = 0; i < currentPoints.length; i++) {
      const p = currentPoints[i]
      const pt = mapInstance.latLngToContainerPoint([p.lat, p.lng])
      if (pt.x < -15 || pt.y < -15 || pt.x > size.x + 15 || pt.y > size.y + 15) continue

      const isMoving = p.status === 'moving'

      if (isMoving && p.plat != null) {
        // 极简微动流线
        const ppt = mapInstance.latLngToContainerPoint([p.plat, p.plng])
        const dx = ppt.x - pt.x
        const dy = ppt.y - pt.y
        const dist = Math.hypot(dx, dy)
        if (dist > 1 && dist < 80) {
          ctx.beginPath()
          ctx.moveTo(ppt.x, ppt.y)
          ctx.lineTo(pt.x, pt.y)
          ctx.strokeStyle = 'rgba(234, 88, 12, 0.4)'
          ctx.lineWidth = 1.8
          ctx.stroke()
        }
      }

      // 实体圆点：极简主义配色，停放为深石墨蓝灰，骑行为精准赫石橙
      ctx.beginPath()
      ctx.arc(pt.x, pt.y, isMoving ? 3.5 : 2.6, 0, Math.PI * 2)
      ctx.fillStyle = isMoving ? '#ea580c' : '#334155'
      ctx.fill()
      ctx.lineWidth = 1
      ctx.strokeStyle = '#ffffff'
      ctx.stroke()
    }
  }

  function animLoop() {
    if (targetPoints.length) {
      const tMap = new Map()
      targetPoints.forEach((tp) => tMap.set(tp.bike_id, tp))
      const visited = new Set()

      currentPoints = currentPoints.map((p) => {
        visited.add(p.bike_id)
        const tgt = tMap.get(p.bike_id)
        if (!tgt) return p
        const ease = 0.28
        return {
          ...p,
          plat: p.lat,
          plng: p.lng,
          lat: p.lat + (tgt.lat - p.lat) * ease,
          lng: p.lng + (tgt.lng - p.lng) * ease,
          status: tgt.status,
          speed: tgt.speed || 0,
        }
      })

      targetPoints.forEach((tp) => {
        if (!visited.has(tp.bike_id)) {
          currentPoints.push({ ...tp, plat: tp.lat, plng: tp.lng })
        }
      })
    }

    renderFrame()
    animId = requestAnimationFrame(animLoop)
  }

  mapInstance.on('move zoom resize viewreset zoomend moveend', () => {
    resize()
    renderFrame()
  })

  resize()
  animId = requestAnimationFrame(animLoop)

  return {
    setPoints(pts) {
      targetPoints = pts || []
      if (!currentPoints.length && targetPoints.length) {
        currentPoints = targetPoints.map((p) => ({ ...p, plat: p.lat, plng: p.lng }))
      }
    },
    setVisible(val) {
      isVisible = val
      if (!val) {
        const size = mapInstance.getSize()
        ctx.clearRect(0, 0, size.x, size.y)
      } else {
        renderFrame()
      }
    },
    destroy() {
      if (animId) cancelAnimationFrame(animId)
      mapInstance.off('move zoom resize viewreset zoomend moveend')
      canvas.remove()
    },
  }
}

/* =========================================================================
   底图与图层组件管理 (精细化建筑制图美学)
   ========================================================================= */
function initMap(cfg) {
  if (mapReady.value || !cfg || !mapEl.value) return
  const rawMap = cfg.map || cfg
  const { top_left, bottom_right } = rawMap
  if (!top_left || !bottom_right) return

  try {
    const southWest = [Math.min(top_left.lat, bottom_right.lat), Math.min(top_left.lng, bottom_right.lng)]
    const northEast = [Math.max(top_left.lat, bottom_right.lat), Math.max(top_left.lng, bottom_right.lng)]
    const bounds = [southWest, northEast]

    map = L.map(mapEl.value, {
      crs: L.CRS.EPSG3857,
      zoomSnap: 0.1,
      zoomControl: false,
      attributionControl: false,
      maxBounds: bounds,
      maxBoundsViscosity: 0.8,
    })

    // 校园地图覆盖
    L.imageOverlay('/campus_map.jpg', bounds, { opacity: 0.96 }).addTo(map)
    map.fitBounds(bounds)

    // 调度指挥中心（极简黑白工业风针脚）
    const depot = (cfg.cvrp && cfg.cvrp.depot) || { lat: 34.143, lng: 108.8415 }
    const depotIcon = L.divIcon({
      className: 'depot-pin-wrap',
      html: `
        <div class="depot-pin">
          <div class="depot-core"></div>
          <span class="depot-tag">调度中心</span>
        </div>
      `,
      iconSize: [80, 24],
      iconAnchor: [40, 12],
    })
    L.marker([depot.lat, depot.lng], { icon: depotIcon, zIndexOffset: 700 }).addTo(map)

    bikeCanvasLayer = createBikeCanvasLayer(map)
    mapReady.value = true

    updateAllLayers()
    setTimeout(() => map && map.invalidateSize(), 150)
    setTimeout(() => map && map.fitBounds(bounds), 400)
  } catch (err) {
    console.error('地图初始化异常:', err)
  }
}

/* 渐变热力图 (高级克制色彩：蓝灰 -> 暖黄 -> 砖红) */
function updateHeatLayer() {
  if (!mapReady.value) return
  if (!props.showHeat || !props.heat || !props.heat.length) {
    if (heatLayer) {
      map.removeLayer(heatLayer)
      heatLayer = null
    }
    return
  }

  const heatData = props.heat.map((h) => [h.lat, h.lng, h.intensity || 0.5])
  if (!heatLayer) {
    heatLayer = L.heatLayer(heatData, {
      radius: 36,
      blur: 24,
      maxZoom: 18,
      max: 1.6,
      gradient: {
        0.15: '#94a3b8',
        0.4: '#60a5fa',
        0.65: '#f59e0b',
        0.85: '#ea580c',
        1.0: '#e11d48',
      },
    }).addTo(map)
  } else {
    heatLayer.setLatLngs(heatData)
  }
}

/* 聚类堆积圈 (Dieter Rams 建筑图纸风圆环 + 瑞士字体标签) */
function updateClusterMarkers() {
  if (!mapReady.value) return
  clusterMarkers.forEach((m) => m.remove())
  clusterMarkers = []
  if (!props.showClusters || !props.clusters) return

  props.clusters.forEach((c) => {
    const isLevel3 = c.level === 3
    const icon = L.divIcon({
      className: 'cluster-pin-container',
      html: `
        <div class="cluster-boundary ${isLevel3 ? 'level-3' : 'level-2'}">
          <div class="boundary-ring"></div>
          <div class="minimal-badge">
            <span class="badge-status-dot"></span>
            <span class="badge-name">${c.name || '聚集簇'}</span>
            <span class="badge-val">${c.count}辆</span>
            <span class="badge-ratio">+${Math.round((c.ratio || 1) * 100 - 100)}%</span>
          </div>
        </div>
      `,
      iconSize: [140, 36],
      iconAnchor: [70, 18],
    })
    const marker = L.marker([c.lat, c.lng], { icon, zIndexOffset: 850 }).addTo(map)
    clusterMarkers.push(marker)
  })
}

/* 空缺区标记 */
function updateShortageMarkers() {
  if (!mapReady.value) return
  shortageMarkers.forEach((m) => m.remove())
  shortageMarkers = []
  if (!props.showClusters || !props.shortages) return

  props.shortages.forEach((s) => {
    const icon = L.divIcon({
      className: 'shortage-pin-container',
      html: `
        <div class="shortage-boundary">
          <div class="shortage-ring"></div>
          <div class="minimal-badge shortage">
            <span class="badge-status-dot purple"></span>
            <span class="badge-name">${s.name}</span>
            <span class="badge-val">余${s.count}辆</span>
            <span class="badge-gap">缺${s.gap || 20}</span>
          </div>
        </div>
      `,
      iconSize: [130, 36],
      iconAnchor: [65, 18],
    })
    const marker = L.marker([s.lat, s.lng], { icon, zIndexOffset: 800 }).addTo(map)
    shortageMarkers.push(marker)
  })
}

/* 调度专车 (Uber / Linear 简约黑色胶囊) */
function updateTruckMarkers() {
  if (!mapReady.value) return
  truckMarkers.forEach((m) => m.remove())
  truckMarkers = []
  if (!props.showTrucks || !props.trucks) return

  props.trucks.forEach((t) => {
    let lat = t.lat
    let lng = t.lng
    if (t.status === 'standby') {
      lat += (t.id === 1 ? 0.00015 : -0.00015)
      lng += (t.id === 1 ? -0.00025 : 0.00025)
    }

    const icon = L.divIcon({
      className: 'truck-pin-container',
      html: `
        <div class="minimal-truck-pill ${t.status}">
          <span class="truck-lead">🚚 ${t.id}号车</span>
          <span class="truck-load-pill">${t.load}/${t.capacity}</span>
          <span class="truck-state-text">${t.status_text || ''}</span>
        </div>
      `,
      iconSize: [120, 26],
      iconAnchor: [60, 13],
    })
    const marker = L.marker([lat, lng], { icon, zIndexOffset: 950 }).addTo(map)
    truckMarkers.push(marker)
  })
}

/* 校园核心热点地标 (极简微型地标，无文字压叠) */
function updateHotspots() {
  if (!mapReady.value) return
  hotspotMarkers.forEach((m) => m.remove())
  hotspotMarkers = []
  if (!props.showHotspots || !props.hotspots) return

  const activeClusterNames = new Set((props.clusters || []).map((c) => c.name))
  const activeShortageNames = new Set((props.shortages || []).map((s) => s.name))

  props.hotspots.forEach((h) => {
    // 若该地标已有动态聚类圈或空缺圈，隐藏静态地标，避免视觉压字
    if (activeClusterNames.has(h.name) || activeShortageNames.has(h.name)) return

    const icon = L.divIcon({
      className: 'hotspot-pin-wrap',
      html: `
        <div class="hotspot-minimal-pin">
          <span class="hs-point"></span>
          <span class="hs-text">${h.name}</span>
        </div>
      `,
      iconSize: [80, 20],
      iconAnchor: [40, 10],
    })
    const marker = L.marker([h.lat, h.lng], { icon, zIndexOffset: 300 }).addTo(map)
    hotspotMarkers.push(marker)
  })
}

/* 调度路线 (纯净几何折线) */
function updateRoutes() {
  if (!mapReady.value) return
  routeLayers.forEach((l) => l.remove())
  routeLayers = []
  if (!props.dispatch || !props.dispatch.routes) return

  const { depot, nodes = [] } = props.dispatch
  props.dispatch.routes.forEach((r) => {
    const latlngs = r.path
      .map((idx) => {
        if (idx === 0) return [depot.lat, depot.lng]
        const nd = nodes[idx - 1]
        return nd ? [nd.lat, nd.lng] : null
      })
      .filter(Boolean)

    if (latlngs.length >= 2) {
      const line = L.polyline(latlngs, {
        color: '#2563eb',
        weight: 2.5,
        opacity: 0.85,
        dashArray: '6 5',
      }).addTo(map)
      routeLayers.push(line)
    }
  })
}

function updateAllLayers() {
  updateHeatLayer()
  updateClusterMarkers()
  updateShortageMarkers()
  updateTruckMarkers()
  updateHotspots()
  updateRoutes()
  if (bikeCanvasLayer) {
    bikeCanvasLayer.setVisible(props.showBikes)
    bikeCanvasLayer.setPoints(props.bikes || [])
  }
}

watch(() => props.config, (cfg) => nextTick(() => initMap(cfg)), { immediate: true })
watch(() => props.bikes, (b) => bikeCanvasLayer && bikeCanvasLayer.setPoints(b || []))
watch(() => props.heat, () => updateHeatLayer(), { deep: true })
watch(() => props.clusters, () => updateClusterMarkers(), { deep: true })
watch(() => props.shortages, () => updateShortageMarkers(), { deep: true })
watch(() => props.trucks, () => updateTruckMarkers(), { deep: true })
watch(() => props.hotspots, () => updateHotspots(), { deep: true })
watch(() => props.dispatch, () => updateRoutes(), { deep: true })
watch(() => props.showHeat, () => updateHeatLayer())
watch(() => props.showClusters, () => { updateClusterMarkers(); updateShortageMarkers() })
watch(() => props.showBikes, (v) => bikeCanvasLayer && bikeCanvasLayer.setVisible(v))
watch(() => props.showTrucks, () => updateTruckMarkers())
watch(() => props.showHotspots, () => updateHotspots())

onBeforeUnmount(() => {
  if (bikeCanvasLayer) bikeCanvasLayer.destroy()
  if (map) {
    map.remove()
    map = null
  }
  mapReady.value = false
})
</script>

<style>
/* 容器及底图 */
.map-view {
  position: relative;
  width: 100%;
  height: 100%;
  background: #f1f5f9;
  overflow: hidden;
}
.map-container {
  width: 100%;
  height: 100%;
  background: #f1f5f9;
}
.map-loading {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  background: rgba(255, 255, 255, 0.9);
  color: #475569;
  font-size: 13px;
  z-index: 1000;
}
.loading-ring {
  width: 28px;
  height: 28px;
  border: 2px solid #cbd5e1;
  border-top-color: #0f172a;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 极简图例 (白底黑字、精细线条、瑞士极简) */
.minimal-legend {
  position: absolute;
  top: 14px;
  left: 14px;
  z-index: 500;
  background: rgba(255, 255, 255, 0.94);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 6px 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}
.legend-row {
  display: flex;
  align-items: center;
  gap: 14px;
}
.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: #475569;
  font-weight: 500;
}
.badge-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  display: inline-block;
}
.dot-surge { background: #e11d48; }
.dot-mid { background: #ea580c; }
.dot-shortage { background: #7c3aed; }
.dot-idle { background: #334155; }
.dot-moving { background: #ea580c; }
.dot-truck { background: #2563eb; }

/* 极简图层切换按键 (Apple Segmented 风格) */
.minimal-layer-controls {
  position: absolute;
  top: 14px;
  right: 14px;
  z-index: 500;
  display: flex;
  background: rgba(255, 255, 255, 0.94);
  backdrop-filter: blur(8px);
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 3px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}
.layer-pill {
  padding: 4px 10px;
  border: none;
  background: transparent;
  color: #64748b;
  font-size: 11px;
  font-weight: 500;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.layer-pill:hover {
  color: #0f172a;
}
.layer-pill.active {
  background: #0f172a;
  color: #ffffff;
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
}

/* 调度中心标识 */
.depot-pin-wrap {
  pointer-events: none;
}
.depot-pin {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: #0f172a;
  color: #fff;
  padding: 3px 8px;
  border-radius: 12px;
  border: 1px solid #ffffff;
  box-shadow: 0 2px 5px rgba(0, 0, 0, 0.15);
}
.depot-core {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #f59e0b;
}
.depot-tag {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.5px;
}

/* 聚类堆积标记：无廉价霓虹发光，纯净建筑圆环与精确标签 */
.cluster-pin-container {
  pointer-events: none;
}
.cluster-boundary {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}
.boundary-ring {
  position: absolute;
  width: 58px;
  height: 58px;
  border-radius: 50%;
  border: 1.5px solid #e11d48;
  background: rgba(225, 29, 72, 0.08);
}
.level-3 .boundary-ring {
  border-width: 2px;
  animation: cleanBreath 2.4s infinite ease-in-out;
}
.level-2 .boundary-ring {
  border-color: #ea580c;
  background: rgba(234, 88, 12, 0.06);
}
@keyframes cleanBreath {
  0%, 100% { transform: scale(0.92); opacity: 0.85; }
  50% { transform: scale(1.15); opacity: 0.45; }
}

.minimal-badge {
  position: relative;
  z-index: 10;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: #ffffff;
  border: 1px solid #e11d48;
  padding: 3px 8px;
  border-radius: 14px;
  box-shadow: 0 2px 6px rgba(225, 29, 72, 0.15);
  color: #0f172a;
  font-size: 11px;
}
.badge-status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #e11d48;
}
.badge-status-dot.purple {
  background: #7c3aed;
}
.badge-name {
  font-weight: 600;
  color: #0f172a;
}
.badge-val {
  font-weight: 700;
  color: #e11d48;
}
.badge-ratio {
  font-size: 10px;
  font-weight: 600;
  color: #be123c;
  background: #ffe4e6;
  padding: 1px 4px;
  border-radius: 3px;
}

/* 空缺区标记 */
.shortage-pin-container {
  pointer-events: none;
}
.shortage-boundary {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}
.shortage-ring {
  position: absolute;
  width: 50px;
  height: 50px;
  border-radius: 50%;
  border: 1.5px dashed #7c3aed;
  background: rgba(124, 58, 237, 0.06);
}
.minimal-badge.shortage {
  border-color: #7c3aed;
  box-shadow: 0 2px 6px rgba(124, 58, 237, 0.15);
}
.badge-gap {
  font-size: 10px;
  font-weight: 600;
  color: #6d28d9;
  background: #ede9fe;
  padding: 1px 4px;
  border-radius: 3px;
}

/* 调度专车胶囊 (Uber Movement 极简风) */
.truck-pin-container {
  pointer-events: none;
}
.minimal-truck-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: #0f172a;
  border: 1px solid #334155;
  color: #ffffff;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 10px;
  box-shadow: 0 2px 5px rgba(0, 0, 0, 0.2);
}
.truck-lead {
  font-weight: 600;
}
.truck-load-pill {
  background: #2563eb;
  color: #fff;
  padding: 1px 4px;
  border-radius: 3px;
  font-weight: 700;
  font-size: 9px;
}
.truck-state-text {
  color: #cbd5e1;
}

/* 地标微型图钉 */
.hotspot-minimal-pin {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid #cbd5e1;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 500;
  color: #334155;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}
.hs-point {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #0f172a;
}
</style>
