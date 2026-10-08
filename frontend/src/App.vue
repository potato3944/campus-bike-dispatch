<template>
  <div class="app-root">
    <!-- 极简大师风导航栏 (Dieter Rams / Apple Studio 风格) -->
    <header class="topbar">
      <div class="brand">
        <div class="brand-symbol">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#0f172a" stroke-width="2.2">
            <circle cx="5.5" cy="17.5" r="3.5" />
            <circle cx="18.5" cy="17.5" r="3.5" />
            <path d="M5.5 17.5L9 9h6l3 8.5M9 9l-1-4H6m3 4h6m0 0l2-4h2" />
          </svg>
        </div>
        <div class="brand-text">
          <h1 class="title">校园共享单车智能调度系统</h1>
          <span class="sub-title">CAMPUS MOBILITY ENGINE · DIGITAL TWIN DISPATCH</span>
        </div>
      </div>

      <!-- 核心场景分段选择器 (Apple Segmented Control) -->
      <div class="scenario-segmented">
        <button
          v-for="sc in scenarioList"
          :key="sc.id"
          class="seg-item"
          :class="{ active: currentScenarioId === sc.id && !isLiveMode }"
          @click="selectScenario(sc.id)"
        >
          {{ sc.title.split('·')[0] }}
        </button>
        <button
          class="seg-item"
          :class="{ active: isLiveMode }"
          @click="switchToLiveMode"
        >
          实时监测
        </button>
      </div>

      <!-- 右侧极简状态 -->
      <div class="top-status">
        <div class="clock-display">
          <span class="clock-label">推演时间</span>
          <span class="clock-time">{{ displayTime }}</span>
        </div>
        <div class="stage-tag" :class="stageClass">
          {{ currentPhaseName }}
        </div>
        <div class="conn-dot-wrap">
          <span class="status-indicator"></span>
          <span class="conn-txt">系统就绪</span>
        </div>
      </div>
    </header>

    <!-- 顶部数据看板条 (Typography-First 极简指标) -->
    <section class="kpi-strip">
      <div class="kpi-cell">
        <div class="cell-label">01 / 在线车辆</div>
        <div class="cell-val">{{ totalBikesCount }}<span class="unit">辆</span></div>
      </div>

      <div class="kpi-cell">
        <div class="cell-label">02 / 骑行流动</div>
        <div class="cell-val">{{ currentFrame?.active_moving ?? 0 }}<span class="unit">辆</span></div>
      </div>

      <div class="kpi-cell" :class="{ alert: (currentFrame?.teaching_total ?? 0) > 180 }">
        <div class="cell-label">03 / 教学区存车</div>
        <div class="cell-val">
          {{ currentFrame?.teaching_total ?? 0 }}<span class="unit">辆</span>
          <span v-if="(currentFrame?.teaching_total ?? 0) > 180" class="mini-tag red">峰值堆积</span>
        </div>
      </div>

      <div class="kpi-cell" :class="{ alert: (currentFrame?.dorm_total ?? 0) < 50 }">
        <div class="cell-label">04 / 宿舍区存车</div>
        <div class="cell-val">
          {{ currentFrame?.dorm_total ?? 0 }}<span class="unit">辆</span>
          <span v-if="(currentFrame?.dorm_total ?? 0) < 50" class="mini-tag purple">排空空缺</span>
        </div>
      </div>

      <div class="kpi-cell">
        <div class="cell-label">05 / 聚类告警</div>
        <div class="cell-val">{{ currentClusters.length }}<span class="unit">处</span></div>
      </div>

      <div class="kpi-cell">
        <div class="cell-label">06 / 调度车辆</div>
        <div class="cell-val">{{ activeTrucksCount }} / {{ mapConfig?.cvrp?.vehicle_num ?? 5 }}<span class="unit">辆</span></div>
      </div>

      <div class="kpi-cell">
        <div class="cell-label">07 / 供需平衡率</div>
        <div class="cell-val">{{ currentFrame?.balance_rate ?? 85.0 }}<span class="unit">%</span></div>
      </div>
    </section>

    <!-- 主视窗工作区 -->
    <main class="workbench">
      <!-- 左侧：热点车位饱和度实时看板与算法诊断 -->
      <aside class="left-panel">
        <div class="content-card hotspot-card">
          <div class="card-header">
            <span class="card-title">区域车位饱和度</span>
            <span class="card-sub-count">10 处核心区域</span>
          </div>
          <div class="hotspot-list">
            <div
              v-for="(cap, name) in capacityMap"
              :key="name"
              class="zone-bar-row"
              :class="getStockStatusClass(name, currentZoneCounts[name] || 0, cap)"
            >
              <div class="zb-meta">
                <span class="zb-name">{{ name }}</span>
                <span class="zb-data">
                  <strong>{{ currentZoneCounts[name] || 0 }}</strong> / {{ cap }}
                  <span class="zb-pct">({{ Math.round(((currentZoneCounts[name] || 0) / cap) * 100) }}%)</span>
                </span>
              </div>
              <div class="zb-line-track">
                <div
                  class="zb-line-fill"
                  :style="{
                    width: Math.min(100, Math.round(((currentZoneCounts[name] || 0) / cap) * 100)) + '%',
                  }"
                ></div>
              </div>
            </div>
          </div>
        </div>

        <div class="content-card diag-card">
          <div class="card-header">
            <span class="card-title">算法引擎状态</span>
          </div>
          <div class="diag-body">
            <div class="diag-row">
              <span class="k">聚类识别</span>
              <span class="v">DBSCAN + K-Means</span>
            </div>
            <div class="diag-row">
              <span class="k">邻域半径 (Eps)</span>
              <span class="v font-mono">{{ mapConfig?.cluster?.eps_m ?? 80 }} m</span>
            </div>
            <div class="diag-row">
              <span class="k">核心密度 (MinPts)</span>
              <span class="v font-mono">{{ mapConfig?.cluster?.min_samples ?? 5 }} 辆</span>
            </div>
            <div class="diag-row">
              <span class="k">路径求解</span>
              <span class="v">{{ solverLabel }}</span>
            </div>
          </div>
        </div>
      </aside>

      <!-- 中间：高保真地图与底部悬浮控制岛 -->
      <section class="center-gis">
        <div class="map-frame">
          <MapView
            :config="mapConfig"
            :hotspots="hotspots"
            :bikes="currentDisplayBikes"
            :clusters="currentClusters"
            :shortages="currentShortages"
            :heat="currentHeat"
            :trucks="currentTrucks"
            :dispatch="dispatchPlan"
            :show-heat="layerShowHeat"
            :show-clusters="layerShowClusters"
            :show-bikes="layerShowBikes"
            :show-trucks="layerShowTrucks"
            :show-hotspots="layerShowHotspots"
            @toggle-layer="onToggleLayer"
          />

          <!-- 底部悬浮控制岛 (Apple Dynamic Island / Media Player 极简风格) -->
          <div class="floating-controller-dock">
            <div class="dock-top-row">
              <div class="phase-info">
                <span class="phase-lead">{{ currentPhaseName }}</span>
                <span class="phase-detail">{{ currentPhaseDesc }}</span>
              </div>
              <div class="time-bookmarks">
                <button class="bm-chip" @click="seekToStep(0)">07:30 起步</button>
                <button class="bm-chip" @click="seekToStep(18)">07:48 潮汐</button>
                <button class="bm-chip alert" @click="seekToStep(32)">08:02 峰值聚集</button>
                <button class="bm-chip truck" @click="seekToStep(42)">08:12 调度削峰</button>
                <button class="bm-chip" @click="seekToStep(56)">08:26 平衡</button>
              </div>
            </div>

            <div class="dock-controls-row">
              <button class="round-play-btn" :class="{ playing }" @click="togglePlay" :title="playing ? '暂停' : '播放'">
                <span class="btn-glyph">{{ playing ? '❚❚' : '▶' }}</span>
              </button>

              <div class="track-slider-group">
                <input
                  type="range"
                  class="dock-slider"
                  min="0"
                  :max="maxSteps"
                  v-model.number="currentStep"
                  @input="onSliderInput"
                />
                <div class="dock-slider-scale">
                  <span>{{ scenarioData?.time_start || '07:30' }}</span>
                  <span class="current-step-label">{{ displayTime }}</span>
                  <span>{{ scenarioData?.time_end || '08:30' }}</span>
                </div>
              </div>

              <div class="speed-toggle-group">
                <button
                  v-for="sp in [1, 2, 5]"
                  :key="sp"
                  class="speed-pill"
                  :class="{ active: playSpeedMultiplier === sp }"
                  @click="playSpeedMultiplier = sp"
                >
                  {{ sp }}×
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- 右侧：实时折线图与调度任务面板 -->
      <aside class="right-panel">
        <SimChart
          :results="simResults"
          :loading="simLoading"
          :frames="scenarioFrames"
          :current-step="currentStep"
          @run="runSimComparison"
        />
        <TaskPanel
          :dispatch="dispatchPlan"
          :trucks="currentTrucks"
          :loading="dispatchLoading"
          @refresh="runCvrpOptimization"
        />
      </aside>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import MapView from './components/MapView.vue'
import TaskPanel from './components/TaskPanel.vue'
import SimChart from './components/SimChart.vue'
import { api, connectGpsWs } from './api.js'

// 基础数据与配置
const mapConfig = ref(null)
const hotspots = ref([])
const isOnline = ref(false)
const dispatchLoading = ref(false)
const simLoading = ref(false)
const simResults = ref([])
const dispatchPlan = ref(null)

// 场景列表
const scenarioList = ref([
  { id: 'morning_rush', title: '早八上课潮·教学区聚集演化', tag: '早高峰聚集' },
  { id: 'noon_canteen', title: '午间就餐潮·食堂门口暴增', tag: '午高峰就餐' },
  { id: 'evening_dorm', title: '晚间归寝流·宿舍潮汐回流', tag: '晚高峰回流' },
  { id: 'dispatch_compare', title: '调度成效比·削峰填谷对照', tag: '算法成效' },
])
const currentScenarioId = ref('morning_rush')
const isLiveMode = ref(false)
const scenarioData = ref(null)
const scenarioFrames = ref([])
const currentStep = ref(0)
const playing = ref(true)
const playSpeedMultiplier = ref(1.0)
let playTimer = null

// 图层开关
const layerShowHeat = ref(true)
const layerShowClusters = ref(true)
const layerShowBikes = ref(true)
const layerShowTrucks = ref(true)
const layerShowHotspots = ref(true)

function onToggleLayer(layer) {
  if (layer === 'heat') layerShowHeat.value = !layerShowHeat.value
  else if (layer === 'clusters') layerShowClusters.value = !layerShowClusters.value
  else if (layer === 'bikes') layerShowBikes.value = !layerShowBikes.value
  else if (layer === 'trucks') layerShowTrucks.value = !layerShowTrucks.value
  else if (layer === 'hotspots') layerShowHotspots.value = !layerShowHotspots.value
}

// 容量映射表
const capacityMap = {
  教学楼主楼区: 60,
  教学楼西区: 50,
  图书馆: 50,
  宿舍区东: 80,
  宿舍区西: 80,
  第一食堂: 60,
  第二食堂: 50,
  中心广场: 50,
  运动场: 40,
  '校门/通勤点': 50,
}

const maxSteps = computed(() => Math.max(0, (scenarioFrames.value?.length || 1) - 1))
const currentFrame = computed(() => scenarioFrames.value[currentStep.value] || null)

const displayTime = computed(() => {
  if (isLiveMode.value) return liveSimTime.value
  return currentFrame.value?.time || '07:30'
})

const currentPhaseName = computed(() => {
  if (isLiveMode.value) return '实时在线监测'
  return currentFrame.value?.phase || '起步分散期'
})

const currentPhaseDesc = computed(() => {
  if (isLiveMode.value) return '正在接收校园单车实时状态'
  return currentFrame.value?.phase_desc || '单车均匀停放于各热点'
})

const stageClass = computed(() => {
  const p = currentPhaseName.value
  if (p.includes('严重堆积') || p.includes('峰值')) return 'alert'
  if (p.includes('调度') || p.includes('削峰')) return 'dispatch'
  if (p.includes('平衡')) return 'safe'
  return 'normal'
})

const totalBikesCount = computed(() => {
  if (isLiveMode.value) return liveBikes.value.length || 350
  return scenarioData.value?.total_bikes || 350
})

const currentDisplayBikes = computed(() => {
  if (isLiveMode.value) return liveBikes.value
  return currentFrame.value?.bikes || []
})

const currentClusters = computed(() => {
  if (isLiveMode.value) return liveClusters.value?.clusters || []
  return currentFrame.value?.clusters || []
})

const currentShortages = computed(() => {
  if (isLiveMode.value) return liveClusters.value?.shortage || []
  return currentFrame.value?.shortages || []
})

const currentHeat = computed(() => {
  if (isLiveMode.value) return liveClusters.value?.heat || []
  return currentFrame.value?.heat || []
})

const currentTrucks = computed(() => {
  if (isLiveMode.value) return []
  return currentFrame.value?.trucks || []
})

const activeTrucksCount = computed(() => {
  return currentTrucks.value.filter(
    (t) => t.status && t.status !== 'standby' && t.status !== 'completed'
  ).length
})

// 当前主求解算法标签（来自后端配置，默认改进遗传算法）
const solverLabel = computed(() => {
  const algo = mapConfig.value?.cvrp?.algorithm || 'ga'
  return algo === 'ortools' ? 'OR-Tools CVRP' : '改进遗传算法 CVRP'
})

const currentZoneCounts = computed(() => {
  if (isLiveMode.value) {
    const counts = {}
    liveBikes.value.forEach((b) => {
      const z = b.zone || b.current_zone
      if (z) counts[z] = (counts[z] || 0) + 1
    })
    return counts
  }
  return currentFrame.value?.zone_counts || {}
})

function getStockStatusClass(name, count, cap) {
  const ratio = count / cap
  if (ratio >= 2.5) return 'surge'
  if (ratio >= 1.4) return 'warning'
  if (ratio < 0.25 && (name.includes('宿舍') || name.includes('校门'))) return 'shortage'
  return 'normal'
}

/* 播放控制器 */
function startPlay() {
  stopPlay()
  const interval = Math.max(80, Math.round(400 / playSpeedMultiplier.value))
  playTimer = setInterval(() => {
    if (currentStep.value >= maxSteps.value) {
      currentStep.value = 0
    } else {
      currentStep.value++
    }
  }, interval)
  playing.value = true
}

function stopPlay() {
  if (playTimer) {
    clearInterval(playTimer)
    playTimer = null
  }
  playing.value = false
}

function togglePlay() {
  if (playing.value) stopPlay()
  else startPlay()
}

function seekToStep(step) {
  currentStep.value = Math.min(maxSteps.value, Math.max(0, step))
}

function onSliderInput() {
  stopPlay()
}

watch(playSpeedMultiplier, () => {
  if (playing.value) startPlay()
})

/* 场景加载 */
async function loadScenario(scenarioId) {
  try {
    currentScenarioId.value = scenarioId
    isLiveMode.value = false
    stopPlay()
    const data = await api.scenarioData(scenarioId, 360, 60)
    scenarioData.value = data
    scenarioFrames.value = data.frames || []
    currentStep.value = 0
    startPlay()
  } catch (err) {
    console.error('加载场景数据异常:', err)
  }
}

function selectScenario(id) {
  loadScenario(id)
}

function switchToLiveMode() {
  isLiveMode.value = true
  stopPlay()
}

/* 实时 WebSocket 模式 */
let ws = null
const liveBikes = ref([])
const liveSimTime = ref('--:--')
const liveClusters = ref(null)

async function runCvrpOptimization() {
  dispatchLoading.value = true
  try {
    dispatchPlan.value = await api.dispatch()
  } catch (e) {
    console.error('CVRP 求解失败', e)
  } finally {
    dispatchLoading.value = false
  }
}

async function runSimComparison() {
  simLoading.value = true
  try {
    const res = await api.simulation()
    simResults.value = res.results || []
  } catch (e) {
    console.error('仿真实验失败', e)
  } finally {
    simLoading.value = false
  }
}

onMounted(async () => {
  try {
    mapConfig.value = await api.config()
    hotspots.value = await api.hotspots()

    const scRes = await api.scenarios()
    if (scRes && scRes.scenarios) {
      scenarioList.value = scRes.scenarios
    }

    await loadScenario('morning_rush')
    runCvrpOptimization()
    runSimComparison()

    ws = connectGpsWs((msg) => {
      isOnline.value = true
      liveSimTime.value = msg.sim_time ? msg.sim_time.substring(11, 16) : '--:--'
      if (isLiveMode.value && msg.points) {
        liveBikes.value = msg.points
        // 后端在 WS 中附带最近一次聚类结果，实时模式据此渲染聚类圈与热力图
        if (msg.clusters) liveClusters.value = msg.clusters
      }
    })
    isOnline.value = true
  } catch (err) {
    console.error('初始化失败:', err)
  }
})

onBeforeUnmount(() => {
  stopPlay()
  if (ws) ws.close()
})
</script>

<style>
/* 极简主义设计系统 (Swiss Design / Apple HIG) */
* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}
html, body, #app {
  height: 100%;
  width: 100%;
  overflow: hidden;
  background: #f8fafc;
  color: #0f172a;
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, "Helvetica Neue", "PingFang SC", sans-serif;
  -webkit-font-smoothing: antialiased;
}

.app-root {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100vw;
  background: #f8fafc;
}

/* 顶部导航栏 (纯净建筑画廊风格) */
.topbar {
  flex: none;
  height: 52px;
  background: #ffffff;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  z-index: 100;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}
.brand-symbol {
  width: 32px;
  height: 32px;
  border-radius: 6px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  display: grid;
  place-items: center;
}
.brand-text .title {
  font-size: 14px;
  font-weight: 600;
  color: #0f172a;
  letter-spacing: -0.2px;
}
.brand-text .sub-title {
  display: block;
  font-size: 9px;
  color: #64748b;
  letter-spacing: 0.5px;
  font-weight: 500;
}

/* 分段场景控制器 (Apple Segmented Control) */
.scenario-segmented {
  display: flex;
  align-items: center;
  background: #f1f5f9;
  padding: 3px;
  border-radius: 7px;
  border: 1px solid #e2e8f0;
}
.seg-item {
  padding: 4px 12px;
  font-size: 11px;
  font-weight: 500;
  color: #64748b;
  border: none;
  background: transparent;
  border-radius: 5px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.seg-item:hover {
  color: #0f172a;
}
.seg-item.active {
  background: #ffffff;
  color: #0f172a;
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

/* 右侧推演状态 */
.top-status {
  display: flex;
  align-items: center;
  gap: 12px;
}
.clock-display {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}
.clock-label {
  font-size: 9px;
  color: #94a3b8;
  text-transform: uppercase;
}
.clock-time {
  font-size: 14px;
  font-weight: 700;
  font-family: monospace;
  color: #0f172a;
}
.stage-tag {
  font-size: 11px;
  font-weight: 500;
  padding: 3px 8px;
  border-radius: 4px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #475569;
}
.stage-tag.alert {
  background: #fff1f2;
  border-color: #fecdd3;
  color: #e11d48;
  font-weight: 600;
}
.stage-tag.dispatch {
  background: #fffbeb;
  border-color: #fde68a;
  color: #d97706;
}
.stage-tag.safe {
  background: #f0fdf4;
  border-color: #bbf7d0;
  color: #16a34a;
}

.conn-dot-wrap {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: #64748b;
}
.status-indicator {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
}

/* 顶部关键指标栏 (Dieter Rams 极简网格) */
.kpi-strip {
  flex: none;
  height: 52px;
  background: #ffffff;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 16px;
  overflow-x: auto;
}
.kpi-cell {
  flex: 1;
  min-width: 120px;
  height: 38px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 0 10px;
  position: relative;
}
.cell-label {
  font-size: 9px;
  color: #64748b;
  font-weight: 500;
  letter-spacing: 0.3px;
}
.cell-val {
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.1;
  display: flex;
  align-items: baseline;
  gap: 4px;
}
.cell-val .unit {
  font-size: 10px;
  color: #94a3b8;
  font-weight: normal;
}
.mini-tag {
  font-size: 9px;
  padding: 0 4px;
  border-radius: 2px;
  font-weight: 600;
}
.mini-tag.red { background: #ffe4e6; color: #e11d48; }
.mini-tag.purple { background: #ede9fe; color: #7c3aed; }

/* 工作台布局 */
.workbench {
  flex: 1;
  display: flex;
  padding: 10px;
  gap: 10px;
  min-height: 0;
  overflow: hidden;
}

/* 左侧面板 */
.left-panel {
  width: 250px;
  flex: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
}
.content-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  display: flex;
  flex-direction: column;
}
.hotspot-card {
  flex: 1;
  min-height: 0;
}
.card-header {
  height: 38px;
  padding: 0 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #f1f5f9;
}
.card-title {
  font-size: 12px;
  font-weight: 600;
  color: #0f172a;
}
.card-sub-count {
  font-size: 10px;
  color: #94a3b8;
}

.hotspot-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.zone-bar-row {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.zb-meta {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
}
.zb-name {
  color: #334155;
  font-weight: 500;
}
.zb-data {
  font-size: 10px;
  color: #64748b;
}
.zb-data strong {
  color: #0f172a;
}
.zb-pct {
  color: #94a3b8;
}

.zb-line-track {
  width: 100%;
  height: 4px;
  border-radius: 2px;
  background: #e2e8f0;
  overflow: hidden;
}
.zb-line-fill {
  height: 100%;
  border-radius: 2px;
  background: #64748b;
  transition: width 0.3s ease;
}
.zone-bar-row.surge .zb-line-fill { background: #e11d48; }
.zone-bar-row.surge .zb-name { color: #e11d48; font-weight: 600; }
.zone-bar-row.warning .zb-line-fill { background: #ea580c; }
.zone-bar-row.shortage .zb-line-fill { background: #7c3aed; }

.diag-card {
  height: 150px;
  flex: none;
}
.diag-body {
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 11px;
}
.diag-row {
  display: flex;
  justify-content: space-between;
  color: #64748b;
  border-bottom: 1px solid #f8fafc;
  padding-bottom: 3px;
}
.diag-row .v { color: #0f172a; font-weight: 500; }
.font-mono { font-family: monospace; }

/* 中间 GIS */
.center-gis {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  position: relative;
}
.map-frame {
  position: relative;
  width: 100%;
  height: 100%;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid #e2e8f0;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

/* 底部悬浮控制岛 (Apple Dynamic Island / Media Player) */
.floating-controller-dock {
  position: absolute;
  bottom: 14px;
  left: 20px;
  right: 20px;
  z-index: 500;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 8px 16px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.dock-top-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #f1f5f9;
  padding-bottom: 5px;
}
.phase-info {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
}
.phase-lead {
  font-weight: 600;
  color: #0f172a;
}
.phase-detail {
  color: #64748b;
}

.time-bookmarks {
  display: flex;
  gap: 5px;
}
.bm-chip {
  padding: 2px 7px;
  border-radius: 4px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #475569;
  font-size: 10px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.bm-chip:hover {
  background: #0f172a;
  color: #ffffff;
  border-color: #0f172a;
}
.bm-chip.alert { border-color: #fecdd3; color: #be123c; }
.bm-chip.truck { border-color: #bbf7d0; color: #15803d; }

.dock-controls-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.round-play-btn {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: none;
  background: #0f172a;
  color: #ffffff;
  display: grid;
  place-items: center;
  cursor: pointer;
  transition: all 0.15s ease;
}
.round-play-btn:hover {
  background: #334155;
  transform: scale(1.05);
}
.round-play-btn.playing {
  background: #e11d48;
}
.btn-glyph {
  font-size: 10px;
  line-height: 1;
}

.track-slider-group {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.dock-slider {
  width: 100%;
  height: 4px;
  border-radius: 2px;
  background: #cbd5e1;
  outline: none;
  cursor: pointer;
  accent-color: #0f172a;
}
.dock-slider-scale {
  display: flex;
  justify-content: space-between;
  font-size: 9px;
  color: #94a3b8;
}
.current-step-label {
  font-weight: 600;
  color: #0f172a;
}

.speed-toggle-group {
  display: flex;
  background: #f1f5f9;
  padding: 2px;
  border-radius: 5px;
  gap: 2px;
}
.speed-pill {
  padding: 2px 6px;
  font-size: 10px;
  border: none;
  background: transparent;
  color: #64748b;
  border-radius: 3px;
  cursor: pointer;
}
.speed-pill.active {
  background: #ffffff;
  color: #0f172a;
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

/* 右侧面板 */
.right-panel {
  width: 340px;
  flex: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
}
</style>
