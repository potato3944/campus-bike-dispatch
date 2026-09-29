<template>
  <div class="map-view">
    <div ref="mapEl" class="map-container"></div>

    <!-- 科技感图层图例与控制卡片 -->
    <div v-if="mapReady" class="map-glass-card top-legend">
      <div class="legend-header">
        <span class="legend-title">图层与态势标识</span>
        <span class="legend-badge">Live GIS</span>
      </div>
      <div class="legend-items">
        <div class="legend-group">
          <span class="lg-chip"><i class="dot red-pulse"></i>严重堆积 (Lv.3)</span>
          <span class="lg-chip"><i class="dot orange-pulse"></i>中度堆积 (Lv.2)</span>
          <span class="lg-chip"><i class="dot yellow-pulse"></i>轻度 (Lv.1)</span>
          <span class="lg-chip"><i class="dot purple-pulse"></i>严重空缺区</span>
        </div>
        <div class="legend-group">
          <span class="lg-chip"><i class="dot bike-idle"></i>停放车辆</span>
          <span class="lg-chip"><i class="dot bike-moving"></i>骑行流动</span>
          <span class="lg-chip"><i class="dot truck-dot"></i>调度专车</span>
        </div>
        <div v-if="showHeat" class="heat-bar-wrap">
          <span class="heat-txt">低密度</span>
          <div class="heat-bar"></div>
          <span class="heat-txt">高密聚集</span>
        </div>
      </div>
    </div>

    <!-- 地图右上角快捷图层开关 -->
    <div v-if="mapReady" class="map-glass-card layer-toggles">
      <button class="layer-btn" :class="{ active: showHeat }" @click="$emit('toggle-layer', 'heat')" title="热力图">
        🔥 热力图
      </button>
      <button class="layer-btn" :class="{ active: showClusters }" @click="$emit('toggle-layer', 'clusters')" title="聚类预警圈">
        ⭕ 聚类光圈
      </button>
      <button class="layer-btn" :class="{ active: showBikes }" @click="$emit('toggle-layer', 'bikes')" title="车辆粒子">
        🚲 车流粒子
      </button>
      <button class="layer-btn" :class="{ active: showTrucks }" @click="$emit('toggle-layer', 'trucks')" title="调度车辆">
        🚚 调度专车
      </button>
    </div>

    <div v-if="!mapReady" class="map-loading">
      <div class="spinner"></div>
      <span>数字孪生校园地图底图加载中…</span>
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
   高性能平滑 Canvas 粒子流渲染引擎 (60 FPS)
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

  let currentPoints = []   // 当前粒子渲染队列 {bike_id, lat, lng, plat, plng, status, speed}
  let targetPoints = []    // 目标粒子位置
  let animId = null
  let isVisible = true

  function resize() {
    const dpr = window.devicePixelRatio || 1
    const size = mapInstance.getSize()
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

    // 绘制全部单车点位与运动拖尾
    for (let i = 0; i < currentPoints.length; i++) {
      const p = currentPoints[i]
      const pt = mapInstance.latLngToContainerPoint([p.lat, p.lng])
      if (pt.x < -20 || pt.y < -20 || pt.x > size.x + 20 || pt.y > size.y + 20) continue

      const isMoving = p.status === 'moving'

      if (isMoving && p.plat != null) {
        // 绘制运动拖尾流光
        const ppt = mapInstance.latLngToContainerPoint([p.plat, p.plng])
        const dx = ppt.x - pt.x
        const dy = ppt.y - pt.y
        const dist = Math.hypot(dx, dy)
        if (dist > 1 && dist < 120) {
          ctx.beginPath()
          ctx.moveTo(ppt.x, ppt.y)
          ctx.lineTo(pt.x, pt.y)
          ctx.strokeStyle = 'rgba(255, 107, 0, 0.45)'
          ctx.lineWidth = 2.2
          ctx.stroke()
        }
      }

      // 绘制粒子外圈光晕
      ctx.beginPath()
      ctx.arc(pt.x, pt.y, isMoving ? 5 : 3.8, 0, Math.PI * 2)
      ctx.fillStyle = isMoving ? 'rgba(255, 107, 0, 0.35)' : 'rgba(0, 240, 255, 0.25)'
      ctx.fill()

      // 绘制粒子实体核心
      ctx.beginPath()
      ctx.arc(pt.x, pt.y, isMoving ? 3.4 : 2.5, 0, Math.PI * 2)
      ctx.fillStyle = isMoving ? '#ff5722' : '#00f0ff'
      ctx.fill()
      ctx.lineWidth = 1
      ctx.strokeStyle = '#ffffff'
      ctx.stroke()
    }
  }

  function animLoop() {
    if (targetPoints.length) {
      // 帧间插值平滑推进
      const tMap = new Map()
      targetPoints.forEach((tp) => tMap.set(tp.bike_id, tp))
      const visited = new Set()

      currentPoints = currentPoints.map((p) => {
        visited.add(p.bike_id)
        const tgt = tMap.get(p.bike_id)
        if (!tgt) return p
        const ease = 0.28 // 平滑插值系数
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

      // 新增点位
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
   地图初始化与各图层渲染
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

    // 添加底图覆盖
    L.imageOverlay('/campus_map.jpg', bounds, { opacity: 0.95 }).addTo(map)
    map.fitBounds(bounds)

    // 添加调度中心标记
    const depot = (cfg.cvrp && cfg.cvrp.depot) || { lat: 34.143, lng: 108.8415 }
    const depotIcon = L.divIcon({
      className: 'depot-pin-wrap',
      html: `
        <div class="depot-marker">
          <div class="depot-pulse"></div>
          <div class="depot-core">⚡</div>
          <span class="depot-label">调度指挥中心</span>
        </div>
      `,
      iconSize: [36, 36],
      iconAnchor: [18, 18],
    })
    L.marker([depot.lat, depot.lng], { icon: depotIcon, zIndexOffset: 800 }).addTo(map)

    bikeCanvasLayer = createBikeCanvasLayer(map)
    mapReady.value = true

    // 触发图层初次绘制
    updateAllLayers()

    // 视角自适应
    setTimeout(() => map && map.invalidateSize(), 150)
    setTimeout(() => map && map.fitBounds(bounds), 400)
  } catch (err) {
    console.error('地图初始化异常:', err)
  }
}

/* 渲染热力图 */
function updateHeatLayer() {
  if (!mapReady.value) return
  if (!props.showHeat || !props.heat || !props.heat.length) {
    if (heatLayer) {
      map.removeLayer(heatLayer)
      heatLayer = null
    }
    return
  }

  const heatData = props.heat.map((h) => [h.lat, h.lng, h.intensity || 0.6])
  if (!heatLayer) {
    heatLayer = L.heatLayer(heatData, {
      radius: 35,
      blur: 24,
      maxZoom: 18,
      max: 1.5,
      gradient: {
        0.15: '#00f0ff',
        0.35: '#00e676',
        0.55: '#ffeb3b',
        0.75: '#ff9800',
        1.0: '#ff1744',
      },
    }).addTo(map)
  } else {
    heatLayer.setLatLngs(heatData)
  }
}

/* 渲染堆积聚类脉冲光圈 */
function updateClusterMarkers() {
  if (!mapReady.value) return
  clusterMarkers.forEach((m) => m.remove())
  clusterMarkers = []
  if (!props.showClusters || !props.clusters) return

  props.clusters.forEach((c) => {
    const levelClass = c.level === 3 ? 'pulse-level-3' : c.level === 2 ? 'pulse-level-2' : 'pulse-level-1'
    const icon = L.divIcon({
      className: 'cluster-pin-container',
      html: `
        <div class="cluster-pulse-ring ${levelClass}">
          <div class="ripple"></div>
          <div class="ripple-outer"></div>
          <div class="cluster-badge">
            <span class="badge-icon">${c.level === 3 ? '🚨' : '⚠️'}</span>
            <div class="badge-txt">
              <strong>${c.name || '聚集簇#' + c.id}</strong>
              <div class="badge-sub">${c.count}辆 · 超容${Math.round((c.ratio || 1) * 100)}%</div>
            </div>
          </div>
        </div>
      `,
      iconSize: [120, 40],
      iconAnchor: [60, 20],
    })
    const marker = L.marker([c.lat, c.lng], { icon, zIndexOffset: 900 }).addTo(map)
    clusterMarkers.push(marker)
  })
}

/* 渲染空缺区预警圈 */
function updateShortageMarkers() {
  if (!mapReady.value) return
  shortageMarkers.forEach((m) => m.remove())
  shortageMarkers = []
  if (!props.showClusters || !props.shortages) return

  props.shortages.forEach((s) => {
    const icon = L.divIcon({
      className: 'shortage-pin-container',
      html: `
        <div class="shortage-pulse-ring">
          <div class="shortage-ripple"></div>
          <div class="shortage-badge">
            <span class="badge-icon">📉</span>
            <div class="badge-txt">
              <strong>${s.name}</strong>
              <div class="badge-sub">仅存${s.count}辆 · 缺口${s.gap || 30}辆</div>
            </div>
          </div>
        </div>
      `,
      iconSize: [110, 36],
      iconAnchor: [55, 18],
    })
    const marker = L.marker([s.lat, s.lng], { icon, zIndexOffset: 850 }).addTo(map)
    shortageMarkers.push(marker)
  })
}

/* 渲染智能调度专车 */
function updateTruckMarkers() {
  if (!mapReady.value) return
  truckMarkers.forEach((m) => m.remove())
  truckMarkers = []
  if (!props.showTrucks || !props.trucks) return

  props.trucks.forEach((t) => {
    const icon = L.divIcon({
      className: 'truck-pin-container',
      html: `
        <div class="truck-marker-wrap ${t.status}">
          <div class="truck-halo"></div>
          <div class="truck-box">
            <span class="truck-icon">🚚</span>
            <span class="truck-load">${t.load}/${t.capacity}</span>
          </div>
          <div class="truck-tag">${t.name} · ${t.status_text || ''}</div>
        </div>
      `,
      iconSize: [100, 36],
      iconAnchor: [50, 18],
    })
    const marker = L.marker([t.lat, t.lng], { icon, zIndexOffset: 999 }).addTo(map)
    truckMarkers.push(marker)
  })
}

/* 渲染校园核心热点地标 */
function updateHotspots() {
  if (!mapReady.value) return
  hotspotMarkers.forEach((m) => m.remove())
  hotspotMarkers = []
  if (!props.showHotspots || !props.hotspots) return

  props.hotspots.forEach((h) => {
    const icon = L.divIcon({
      className: 'hotspot-pin-wrap',
      html: `
        <div class="hotspot-pin">
          <div class="hotspot-dot"></div>
          <span class="hotspot-label">${h.name}</span>
        </div>
      `,
      iconSize: [80, 24],
      iconAnchor: [40, 12],
    })
    const marker = L.marker([h.lat, h.lng], { icon, zIndexOffset: 400 }).addTo(map)
    marker.bindPopup(`
      <div style="font-size:13px; font-weight:600; color:#111;">${h.name}</div>
      <div style="font-size:12px; color:#666; margin-top:4px;">基准容量: 60 辆 · 权重: ${h.weight}</div>
    `)
    hotspotMarkers.push(marker)
  })
}

/* 渲染调度优化路线 */
function updateRoutes() {
  if (!mapReady.value) return
  routeLayers.forEach((l) => l.remove())
  routeLayers = []
  if (!props.dispatch || !props.dispatch.routes) return

  const colors = ['#00f0ff', '#ff5722', '#10b981', '#a855f7', '#f59e0b']
  const { depot, nodes = [] } = props.dispatch

  props.dispatch.routes.forEach((r, i) => {
    const color = colors[i % colors.length]
    const latlngs = r.path
      .map((idx) => {
        if (idx === 0) return [depot.lat, depot.lng]
        const nd = nodes[idx - 1]
        return nd ? [nd.lat, nd.lng] : null
      })
      .filter(Boolean)

    if (latlngs.length >= 2) {
      const line = L.polyline(latlngs, {
        color,
        weight: 3.5,
        opacity: 0.9,
        dashArray: '8 6',
        lineCap: 'round',
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

// 属性监听
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
/* Leaflet 基础样式与自定义覆盖 */
.map-view {
  position: relative;
  width: 100%;
  height: 100%;
  background: #090e17;
  overflow: hidden;
}
.map-container {
  width: 100%;
  height: 100%;
  background: #090e17;
}
.map-loading {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  background: rgba(9, 14, 23, 0.95);
  color: #00f0ff;
  font-size: 14px;
  font-weight: 500;
  z-index: 1000;
}
.spinner {
  width: 38px;
  height: 38px;
  border: 3px solid rgba(0, 240, 255, 0.2);
  border-top-color: #00f0ff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 磨砂玻璃浮动卡片 */
.map-glass-card {
  position: absolute;
  z-index: 999;
  background: rgba(14, 20, 36, 0.82);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(0, 240, 255, 0.2);
  border-radius: 8px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.45);
  color: #e2e8f0;
}

/* 图例卡片 */
.top-legend {
  top: 14px;
  left: 14px;
  padding: 10px 14px;
  font-size: 12px;
  max-width: 320px;
}
.legend-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.legend-title {
  font-weight: 600;
  font-size: 12px;
  color: #94a3b8;
  letter-spacing: 0.5px;
}
.legend-badge {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(0, 240, 255, 0.15);
  color: #00f0ff;
  font-weight: 600;
}
.legend-items {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.legend-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.lg-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: #cbd5e1;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.dot.red-pulse { background: #ff3366; box-shadow: 0 0 6px #ff3366; }
.dot.orange-pulse { background: #fa8c16; box-shadow: 0 0 6px #fa8c16; }
.dot.yellow-pulse { background: #fadb14; }
.dot.purple-pulse { background: #a855f7; box-shadow: 0 0 6px #a855f7; }
.dot.bike-idle { background: #00f0ff; }
.dot.bike-moving { background: #ff5722; }
.dot.truck-dot { background: #10b981; }

.heat-bar-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}
.heat-txt { font-size: 10px; color: #94a3b8; }
.heat-bar {
  flex: 1;
  height: 6px;
  border-radius: 3px;
  background: linear-gradient(to right, #00f0ff, #00e676, #ffeb3b, #ff9800, #ff1744);
}

/* 图层快捷开关 */
.layer-toggles {
  top: 14px;
  right: 14px;
  padding: 6px 8px;
  display: flex;
  gap: 6px;
}
.layer-btn {
  padding: 5px 10px;
  border-radius: 5px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.05);
  color: #94a3b8;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}
.layer-btn:hover {
  background: rgba(0, 240, 255, 0.12);
  color: #00f0ff;
  border-color: rgba(0, 240, 255, 0.3);
}
.layer-btn.active {
  background: rgba(0, 240, 255, 0.2);
  color: #00f0ff;
  border-color: #00f0ff;
  box-shadow: 0 0 10px rgba(0, 240, 255, 0.25);
}

/* 调度中心标记 */
.depot-pin-wrap {
  position: relative;
}
.depot-marker {
  position: relative;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.depot-core {
  width: 28px;
  height: 28px;
  background: linear-gradient(135deg, #f59e0b, #d97706);
  border: 2px solid #fff;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 14px;
  color: #fff;
  box-shadow: 0 0 14px #f59e0b;
  z-index: 2;
}
.depot-pulse {
  position: absolute;
  width: 48px;
  height: 48px;
  border-radius: 50%;
  border: 2px solid #f59e0b;
  opacity: 0.8;
  animation: depotPulse 2s infinite ease-out;
}
@keyframes depotPulse {
  0% { transform: scale(0.6); opacity: 1; }
  100% { transform: scale(1.6); opacity: 0; }
}
.depot-label {
  position: absolute;
  top: 32px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(15, 23, 42, 0.85);
  color: #f59e0b;
  font-size: 10px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 3px;
  white-space: nowrap;
  border: 1px solid rgba(245, 158, 11, 0.4);
}

/* 聚类堆积光圈 (DBSCAN / K-Means) */
.cluster-pin-container {
  pointer-events: none;
}
.cluster-pulse-ring {
  position: relative;
  width: 120px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.cluster-badge {
  position: relative;
  z-index: 10;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  border-radius: 16px;
  background: rgba(15, 23, 42, 0.92);
  border: 1.5px solid #ff3366;
  box-shadow: 0 0 16px rgba(255, 51, 102, 0.6);
  color: #fff;
}
.badge-icon { font-size: 12px; }
.badge-txt { font-size: 11px; line-height: 1.2; text-align: left; }
.badge-txt strong { display: block; font-size: 11px; color: #fff; }
.badge-sub { font-size: 9px; color: #ff85a0; font-weight: 600; }

.ripple, .ripple-outer {
  position: absolute;
  border-radius: 50%;
  pointer-events: none;
}
.pulse-level-3 .ripple {
  width: 60px;
  height: 60px;
  border: 2.5px solid #ff3366;
  animation: clusterPulse 1.8s infinite cubic-bezier(0.2, 0.8, 0.2, 1);
}
.pulse-level-3 .ripple-outer {
  width: 90px;
  height: 90px;
  border: 1.5px dashed #ff3366;
  animation: clusterPulse 1.8s infinite 0.6s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.pulse-level-2 .cluster-badge {
  border-color: #fa8c16;
  box-shadow: 0 0 14px rgba(250, 140, 22, 0.5);
}
.pulse-level-2 .badge-sub { color: #ffd591; }
.pulse-level-2 .ripple {
  width: 50px;
  height: 50px;
  border: 2px solid #fa8c16;
  animation: clusterPulse 2.2s infinite ease-out;
}
.pulse-level-1 .cluster-badge {
  border-color: #fadb14;
  box-shadow: 0 0 10px rgba(250, 219, 20, 0.4);
}
.pulse-level-1 .badge-sub { color: #fffb8f; }

@keyframes clusterPulse {
  0% { transform: scale(0.4); opacity: 0.9; }
  100% { transform: scale(1.5); opacity: 0; }
}

/* 空缺区光圈 */
.shortage-pulse-ring {
  position: relative;
  width: 110px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.shortage-badge {
  position: relative;
  z-index: 10;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 7px;
  border-radius: 14px;
  background: rgba(15, 23, 42, 0.9);
  border: 1.5px solid #a855f7;
  box-shadow: 0 0 14px rgba(168, 85, 247, 0.6);
  color: #fff;
}
.shortage-badge .badge-sub { color: #d8b4fe; font-size: 9px; font-weight: 600; }
.shortage-ripple {
  position: absolute;
  width: 50px;
  height: 50px;
  border-radius: 50%;
  border: 2px solid #a855f7;
  animation: clusterPulse 2.5s infinite ease-out;
}

/* 调度专车标记 */
.truck-pin-container {
  pointer-events: none;
}
.truck-marker-wrap {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.truck-box {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  background: linear-gradient(135deg, #10b981, #059669);
  border: 2px solid #fff;
  border-radius: 14px;
  padding: 2px 7px;
  box-shadow: 0 0 14px rgba(16, 185, 129, 0.8);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  z-index: 5;
}
.truck-tag {
  background: rgba(15, 23, 42, 0.88);
  border: 1px solid rgba(16, 185, 129, 0.4);
  color: #a7f3d0;
  font-size: 9px;
  font-weight: 600;
  padding: 1px 5px;
  border-radius: 3px;
  margin-top: 2px;
  white-space: nowrap;
}
.truck-halo {
  position: absolute;
  width: 44px;
  height: 44px;
  top: -8px;
  border-radius: 50%;
  border: 1.5px dashed #10b981;
  animation: rotateSpin 6s linear infinite;
}
@keyframes rotateSpin {
  to { transform: rotate(360deg); }
}

/* 校园地标图钉 */
.hotspot-pin-wrap {
  pointer-events: auto;
}
.hotspot-pin {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: rgba(15, 23, 42, 0.75);
  border: 1px solid rgba(255, 255, 255, 0.2);
  padding: 2px 6px;
  border-radius: 4px;
  color: #e2e8f0;
  font-size: 10px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}
.hotspot-pin:hover {
  background: rgba(0, 240, 255, 0.25);
  border-color: #00f0ff;
  color: #fff;
  transform: scale(1.08);
}
.hotspot-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #00f0ff;
  box-shadow: 0 0 6px #00f0ff;
}
</style>
