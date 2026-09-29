<template>
  <div class="app-root">
    <!-- 顶部高科技导航栏 -->
    <header class="topbar">
      <div class="brand">
        <div class="logo-box">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#00f0ff" stroke-width="2.2">
            <circle cx="5.5" cy="17.5" r="3.5" />
            <circle cx="18.5" cy="17.5" r="3.5" />
            <path d="M5.5 17.5L9 9h6l3 8.5M9 9l-1-4H6m3 4h6m0 0l2-4h2" />
          </svg>
        </div>
        <div class="brand-text">
          <h1 class="title">智慧校园共享单车智能调度管理平台</h1>
          <span class="sub-title">CAMPUS SMART BIKE DISPATCH & DIGITAL TWIN SYSTEM</span>
        </div>
      </div>

      <!-- 核心场景快捷切换胶囊 -->
      <div class="scenario-selector">
        <button
          v-for="sc in scenarioList"
          :key="sc.id"
          class="sc-pill"
          :class="{ active: currentScenarioId === sc.id && !isLiveMode }"
          @click="selectScenario(sc.id)"
        >
          <span class="sc-dot" :style="{ backgroundColor: sc.accent_color }"></span>
          <span class="sc-name">{{ sc.title.split('·')[0] }}</span>
        </button>
        <button
          class="sc-pill live-pill"
          :class="{ active: isLiveMode }"
          @click="switchToLiveMode"
        >
          <span class="sc-dot live"></span>
          <span class="sc-name">📡 实时数据流</span>
        </button>
      </div>

      <!-- 右侧态势时钟与状态 -->
      <div class="top-status">
        <div class="clock-badge">
          <span class="clock-label">演化时间</span>
          <span class="clock-val">{{ displayTime }}</span>
        </div>
        <div class="phase-badge" :class="phaseClass">
          {{ currentPhaseName }}
        </div>
        <div class="conn-badge" :class="{ online: isOnline }">
          <span class="pulse-dot"></span>{{ isOnline ? '数字孪生已就绪' : '连接中' }}
        </div>
      </div>
    </header>

    <!-- 顶部核心 KPI 指标卡片条 -->
    <section class="kpi-strip">
      <div class="kpi-card cyan">
        <div class="kpi-icon">🚲</div>
        <div class="kpi-info">
          <div class="kpi-label">全校单车总量</div>
          <div class="kpi-val">{{ totalBikesCount }}<span class="unit">辆</span></div>
        </div>
      </div>

      <div class="kpi-card orange">
        <div class="kpi-icon">⚡</div>
        <div class="kpi-info">
          <div class="kpi-label">活跃骑行流动</div>
          <div class="kpi-val">{{ currentFrame?.active_moving ?? 0 }}<span class="unit">辆</span></div>
        </div>
      </div>

      <div class="kpi-card red" :class="{ alert: (currentFrame?.teaching_total ?? 0) > 180 }">
        <div class="kpi-icon">🏫</div>
        <div class="kpi-info">
          <div class="kpi-label">教学区存车量 (聚集峰值)</div>
          <div class="kpi-val">{{ currentFrame?.teaching_total ?? 0 }}<span class="unit">辆</span></div>
        </div>
        <span v-if="(currentFrame?.teaching_total ?? 0) > 180" class="kpi-tag alert">严重堆积</span>
      </div>

      <div class="kpi-card purple" :class="{ alert: (currentFrame?.dorm_total ?? 0) < 50 }">
        <div class="kpi-icon">🏢</div>
        <div class="kpi-info">
          <div class="kpi-label">宿舍区存车量 (潮汐排空)</div>
          <div class="kpi-val">{{ currentFrame?.dorm_total ?? 0 }}<span class="unit">辆</span></div>
        </div>
        <span v-if="(currentFrame?.dorm_total ?? 0) < 50" class="kpi-tag purple">严重空缺</span>
      </div>

      <div class="kpi-card amber">
        <div class="kpi-icon">⭕</div>
        <div class="kpi-info">
          <div class="kpi-label">DBSCAN 堆积簇</div>
          <div class="kpi-val">{{ currentClusters.length }}<span class="unit">处</span></div>
        </div>
      </div>

      <div class="kpi-card green">
        <div class="kpi-icon">🚚</div>
        <div class="kpi-info">
          <div class="kpi-label">调度专车出勤</div>
          <div class="kpi-val">{{ activeTrucksCount }} / 2<span class="unit">辆</span></div>
        </div>
      </div>

      <div class="kpi-card emerald">
        <div class="kpi-icon">⚖️</div>
        <div class="kpi-info">
          <div class="kpi-label">全校供需平衡指数</div>
          <div class="kpi-val">{{ currentFrame?.balance_rate ?? 85.0 }}<span class="unit">%</span></div>
        </div>
      </div>
    </section>

    <!-- 主视窗工作区 -->
    <main class="workbench">
      <!-- 左侧：全校热点车位饱和度实时条与算法指标 -->
      <aside class="left-panel">
        <div class="panel hotspot-panel">
          <div class="panel-header">
            <span class="panel-title">📍 校园核心区域存车与容量饱和度</span>
            <span class="badge-live">Live</span>
          </div>
          <div class="panel-body hotspot-list">
            <div
              v-for="(cap, name) in capacityMap"
              :key="name"
              class="hotspot-bar-item"
              :class="getStockStatusClass(name, currentZoneCounts[name] || 0, cap)"
            >
              <div class="hb-title">
                <span class="hb-name">{{ name }}</span>
                <span class="hb-num">
                  <strong>{{ currentZoneCounts[name] || 0 }}</strong> / {{ cap }} 辆
                  <span class="pct">({{ Math.round(((currentZoneCounts[name] || 0) / cap) * 100) }}%)</span>
                </span>
              </div>
              <div class="hb-track">
                <div
                  class="hb-fill"
                  :style="{
                    width: Math.min(100, Math.round(((currentZoneCounts[name] || 0) / cap) * 100)) + '%',
                  }"
                ></div>
              </div>
            </div>
          </div>
        </div>

        <div class="panel diag-panel">
          <div class="panel-header">
            <span class="panel-title">🤖 智能聚类与调度算法决策状态</span>
          </div>
          <div class="panel-body diag-content">
            <div class="diag-item">
              <span class="diag-k">聚类算法核心</span>
              <span class="diag-v highlight">DBSCAN + K-Means 双阶段</span>
            </div>
            <div class="diag-item">
              <span class="diag-k">邻域半径 (Eps)</span>
              <span class="diag-v">80.0 米 (校园尺度)</span>
            </div>
            <div class="diag-item">
              <span class="diag-k">核心点密度 (MinPts)</span>
              <span class="diag-v">5 辆</span>
            </div>
            <div class="diag-item">
              <span class="diag-k">CVRP 求解引擎</span>
              <span class="diag-v highlight">Google OR-Tools (局部引导搜索)</span>
            </div>
            <div class="diag-item">
              <span class="diag-k">当前调度响应阈值</span>
              <span class="diag-v">区域超载 150% 即触发削峰</span>
            </div>
          </div>
        </div>
      </aside>

      <!-- 中间：高保真数字孪生地图与底部时空控制器 -->
      <section class="center-gis">
        <div class="map-wrapper">
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

          <!-- 底部浮动时空推演与演化控制器 -->
          <div class="floating-timeline-bar">
            <!-- 场景提示横幅 -->
            <div class="timeline-banner">
              <div class="tb-left">
                <span class="tb-badge">{{ currentScenarioMeta?.tag || '演化回放' }}</span>
                <span class="tb-desc"><strong>{{ currentPhaseName }}</strong> · {{ currentPhaseDesc }}</span>
              </div>
              <div class="tb-bookmarks">
                <button class="bm-btn" @click="seekToStep(0)">起步 07:30</button>
                <button class="bm-btn" @click="seekToStep(18)">潮汐爆发 07:48</button>
                <button class="bm-btn alert" @click="seekToStep(32)">🚨 严重聚集 08:02</button>
                <button class="bm-btn truck" @click="seekToStep(42)">🚚 调度削峰 08:12</button>
                <button class="bm-btn safe" @click="seekToStep(56)">恢复平衡 08:26</button>
              </div>
            </div>

            <!-- 控制滑块与播放按键 -->
            <div class="timeline-controls">
              <button class="play-btn" :class="{ playing }" @click="togglePlay">
                <span class="play-icon">{{ playing ? '⏸' : '▶' }}</span>
                <span>{{ playing ? '暂停' : '播放演化' }}</span>
              </button>

              <div class="slider-wrapper">
                <input
                  type="range"
                  class="timeline-slider"
                  min="0"
                  :max="maxSteps"
                  v-model.number="currentStep"
                  @input="onSliderInput"
                />
                <div class="slider-ticks">
                  <span>{{ scenarioData?.time_start || '07:30' }} (起点)</span>
                  <span class="center-tick">当前进度 {{ Math.round((currentStep / maxSteps) * 100) }}%</span>
                  <span>{{ scenarioData?.time_end || '08:30' }} (终点)</span>
                </div>
              </div>

              <div class="speed-selector">
                <span class="sp-label">速率:</span>
                <button
                  v-for="sp in [0.5, 1, 2, 5]"
                  :key="sp"
                  class="sp-btn"
                  :class="{ active: playSpeedMultiplier === sp }"
                  @click="playSpeedMultiplier = sp"
                >
                  {{ sp }}x
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- 右侧：实时聚集演化折线趋势图与调度专车任务流水 -->
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

// 场景演化状态
const scenarioList = ref([
  { id: 'morning_rush', title: '早八上课潮·教学区聚集演化', accent_color: '#ff4d4f', tag: '早高峰重度聚集' },
  { id: 'noon_canteen', title: '午间干饭潮·食堂门口暴增', accent_color: '#fa8c16', tag: '午高峰餐饮潮汐' },
  { id: 'evening_dorm', title: '晚间自习归寝·宿舍潮汐回流', accent_color: '#722ed1', tag: '晚高峰反向潮汐' },
  { id: 'dispatch_compare', title: '调度对比·削峰填谷效果评估', accent_color: '#13c2c2', tag: 'CVRP算法成效' },
])
const currentScenarioId = ref('morning_rush')
const isLiveMode = ref(false)
const scenarioData = ref(null)
const scenarioFrames = ref([])
const currentStep = ref(0)
const playing = ref(true)
const playSpeedMultiplier = ref(1.0)
let playTimer = null

// 图层开关控制
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

// 区域容量常量表
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
  if (isLiveMode.value) return '实时在线监控中'
  return currentFrame.value?.phase || '起步分散期'
})

const currentPhaseDesc = computed(() => {
  if (isLiveMode.value) return '正在接收校园边缘计算节点上传的实时单车位置数据流'
  return currentFrame.value?.phase_desc || '单车均匀停放于各热点'
})

const phaseClass = computed(() => {
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

const currentScenarioMeta = computed(() => {
  return scenarioList.value.find((s) => s.id === currentScenarioId.value)
})

function getStockStatusClass(name, count, cap) {
  const ratio = count / cap
  if (ratio >= 2.5) return 'danger'
  if (ratio >= 1.5) return 'warning'
  if (ratio < 0.2 && (name.includes('宿舍') || name.includes('校门'))) return 'shortage'
  return 'normal'
}

/* 播放控制器 */
function startPlay() {
  stopPlay()
  const interval = Math.max(80, Math.round(400 / playSpeedMultiplier.value))
  playTimer = setInterval(() => {
    if (currentStep.value >= maxSteps.value) {
      currentStep.value = 0 // 循环播放
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
  // 拖动滑块时暂停以便细看
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
    // 1. 获取配置与热点
    mapConfig.value = await api.config()
    hotspots.value = await api.hotspots()

    // 2. 获取场景元信息列表
    const scRes = await api.scenarios()
    scenarioList.value = scRes.scenarios || []

    // 3. 默认启动早高峰教学区聚集场景
    await loadScenario('morning_rush')

    // 4. 初次预跑一次 CVRP 和仿真对比
    runCvrpOptimization()
    runSimComparison()

    // 5. 挂接实时 WS 通道
    ws = connectGpsWs((msg) => {
      isOnline.value = true
      liveSimTime.value = msg.sim_time ? msg.sim_time.substring(11, 16) : '--:--'
      if (isLiveMode.value && msg.points) {
        liveBikes.value = msg.points
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
/* 全局重置与深色高科技基调 */
* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}
html, body, #app {
  height: 100%;
  width: 100%;
  overflow: hidden;
  background: #090e17;
  color: #e2e8f0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
  user-select: none;
}

.app-root {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100vw;
  background: radial-gradient(circle at 50% 10%, #111a2e 0%, #080c14 100%);
}

/* 顶部科技导航 */
.topbar {
  flex: none;
  height: 56px;
  background: rgba(14, 20, 36, 0.9);
  backdrop-filter: blur(14px);
  border-bottom: 1px solid rgba(0, 240, 255, 0.2);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 18px;
  z-index: 100;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}
.logo-box {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: rgba(0, 240, 255, 0.12);
  border: 1px solid rgba(0, 240, 255, 0.35);
  display: grid;
  place-items: center;
  box-shadow: 0 0 12px rgba(0, 240, 255, 0.25);
}
.brand-text .title {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.8px;
  color: #f8fafc;
  background: linear-gradient(to right, #ffffff, #00f0ff);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
.brand-text .sub-title {
  display: block;
  font-size: 9px;
  color: #64748b;
  letter-spacing: 1px;
}

/* 场景胶囊 */
.scenario-selector {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(15, 23, 42, 0.6);
  padding: 3px 6px;
  border-radius: 20px;
  border: 1px solid rgba(255, 255, 255, 0.1);
}
.sc-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 16px;
  border: 1px solid transparent;
  background: transparent;
  color: #94a3b8;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}
.sc-pill:hover {
  color: #e2e8f0;
  background: rgba(255, 255, 255, 0.05);
}
.sc-pill.active {
  background: rgba(0, 240, 255, 0.15);
  border-color: rgba(0, 240, 255, 0.4);
  color: #00f0ff;
  font-weight: 600;
  box-shadow: 0 0 10px rgba(0, 240, 255, 0.25);
}
.sc-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}
.sc-dot.live {
  background: #10b981;
  box-shadow: 0 0 6px #10b981;
}

/* 右侧时钟与状态 */
.top-status {
  display: flex;
  align-items: center;
  gap: 12px;
}
.clock-badge {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}
.clock-label {
  font-size: 9px;
  color: #64748b;
  text-transform: uppercase;
}
.clock-val {
  font-size: 16px;
  font-weight: 700;
  font-family: monospace;
  color: #00f0ff;
  text-shadow: 0 0 8px rgba(0, 240, 255, 0.4);
}
.phase-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.15);
}
.phase-badge.alert {
  background: rgba(255, 51, 102, 0.2);
  border-color: #ff3366;
  color: #ff3366;
  box-shadow: 0 0 12px rgba(255, 51, 102, 0.4);
  animation: pulseBlink 1.5s infinite;
}
.phase-badge.dispatch {
  background: rgba(245, 158, 11, 0.2);
  border-color: #f59e0b;
  color: #f59e0b;
}
.phase-badge.safe {
  background: rgba(16, 185, 129, 0.2);
  border-color: #10b981;
  color: #10b981;
}
.phase-badge.normal {
  background: rgba(56, 189, 248, 0.15);
  color: #38bdf8;
}
@keyframes pulseBlink {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.85; transform: scale(1.03); }
}

.conn-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: #94a3b8;
  padding: 3px 8px;
  background: rgba(15, 23, 42, 0.5);
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.conn-badge.online {
  color: #10b981;
}
.pulse-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 6px #10b981;
}

/* 顶部核心 KPI 栏 */
.kpi-strip {
  flex: none;
  height: 64px;
  background: rgba(10, 15, 26, 0.7);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 18px;
  overflow-x: auto;
}
.kpi-card {
  flex: 1;
  min-width: 140px;
  height: 48px;
  background: rgba(15, 23, 42, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 7px;
  display: flex;
  align-items: center;
  padding: 0 12px;
  gap: 10px;
  position: relative;
  overflow: hidden;
  transition: all 0.2s ease;
}
.kpi-card:hover {
  border-color: rgba(0, 240, 255, 0.3);
  transform: translateY(-1px);
}
.kpi-card.cyan { border-left: 3px solid #00f0ff; }
.kpi-card.orange { border-left: 3px solid #f59e0b; }
.kpi-card.red { border-left: 3px solid #ff3366; }
.kpi-card.purple { border-left: 3px solid #a855f7; }
.kpi-card.amber { border-left: 3px solid #fbbf24; }
.kpi-card.green { border-left: 3px solid #10b981; }
.kpi-card.emerald { border-left: 3px solid #34d399; }
.kpi-card.alert {
  box-shadow: 0 0 12px rgba(255, 51, 102, 0.25);
  border-color: rgba(255, 51, 102, 0.5);
}
.kpi-icon {
  font-size: 20px;
}
.kpi-info {
  display: flex;
  flex-direction: column;
}
.kpi-label {
  font-size: 10px;
  color: #94a3b8;
  white-space: nowrap;
}
.kpi-val {
  font-size: 17px;
  font-weight: 700;
  color: #f8fafc;
  line-height: 1.1;
}
.kpi-val .unit {
  font-size: 10px;
  color: #94a3b8;
  font-weight: normal;
  margin-left: 3px;
}
.kpi-tag {
  position: absolute;
  top: 4px;
  right: 6px;
  font-size: 9px;
  padding: 1px 4px;
  border-radius: 3px;
  font-weight: 700;
}
.kpi-tag.alert {
  background: rgba(255, 51, 102, 0.25);
  color: #ff3366;
}
.kpi-tag.purple {
  background: rgba(168, 85, 247, 0.25);
  color: #a855f7;
}

/* 主工作台布局 (左 260px / 中 自适应 / 右 360px) */
.workbench {
  flex: 1;
  display: flex;
  padding: 12px;
  gap: 12px;
  min-height: 0;
  overflow: hidden;
}

/* 左侧面板 */
.left-panel {
  width: 270px;
  flex: none;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
}
.hotspot-panel {
  flex: 1;
  background: rgba(14, 20, 36, 0.82);
  border: 1px solid rgba(0, 240, 255, 0.18);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.hotspot-list {
  flex: 1;
  overflow-y: auto;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 9px;
}
.hotspot-bar-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.hb-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
}
.hb-name {
  color: #cbd5e1;
  font-weight: 500;
}
.hb-num {
  font-size: 10px;
  color: #94a3b8;
}
.hb-num strong {
  color: #f8fafc;
  font-size: 11px;
}
.hb-num .pct {
  color: #64748b;
  margin-left: 2px;
}
.hb-track {
  width: 100%;
  height: 6px;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.08);
  overflow: hidden;
}
.hb-fill {
  height: 100%;
  border-radius: 3px;
  background: #38bdf8;
  transition: width 0.3s ease;
}
/* 状态样式 */
.hotspot-bar-item.danger .hb-fill {
  background: linear-gradient(to right, #fa8c16, #ff3366);
  box-shadow: 0 0 8px #ff3366;
}
.hotspot-bar-item.danger .hb-name { color: #ff3366; font-weight: 700; }
.hotspot-bar-item.warning .hb-fill { background: #f59e0b; }
.hotspot-bar-item.warning .hb-name { color: #f59e0b; }
.hotspot-bar-item.shortage .hb-fill { background: #a855f7; }
.hotspot-bar-item.shortage .hb-name { color: #c084fc; font-weight: 600; }

.diag-panel {
  height: 180px;
  flex: none;
  background: rgba(14, 20, 36, 0.82);
  border: 1px solid rgba(0, 240, 255, 0.18);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
}
.diag-content {
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 7px;
  font-size: 11px;
}
.diag-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px dashed rgba(255, 255, 255, 0.05);
  padding-bottom: 4px;
}
.diag-k { color: #94a3b8; }
.diag-v { color: #e2e8f0; font-weight: 500; }
.diag-v.highlight { color: #00f0ff; font-weight: 600; }

/* 中部 GIS 工作区 */
.center-gis {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  position: relative;
}
.map-wrapper {
  position: relative;
  width: 100%;
  height: 100%;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid rgba(0, 240, 255, 0.25);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
}

/* 底部浮动时空控制器 */
.floating-timeline-bar {
  position: absolute;
  bottom: 14px;
  left: 14px;
  right: 14px;
  z-index: 999;
  background: rgba(14, 20, 36, 0.9);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border: 1px solid rgba(0, 240, 255, 0.3);
  border-radius: 10px;
  padding: 10px 16px;
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.6);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.timeline-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  padding-bottom: 6px;
}
.tb-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.tb-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 4px;
  background: rgba(0, 240, 255, 0.2);
  color: #00f0ff;
  border: 1px solid rgba(0, 240, 255, 0.4);
}
.tb-desc {
  font-size: 11px;
  color: #e2e8f0;
}
.tb-desc strong {
  color: #00f0ff;
}
.tb-bookmarks {
  display: flex;
  gap: 6px;
}
.bm-btn {
  font-size: 10px;
  padding: 3px 8px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: #cbd5e1;
  cursor: pointer;
  transition: all 0.15s;
}
.bm-btn:hover {
  background: rgba(0, 240, 255, 0.2);
  color: #00f0ff;
  border-color: #00f0ff;
}
.bm-btn.alert { border-color: rgba(255, 51, 102, 0.5); color: #ff85a0; }
.bm-btn.alert:hover { background: rgba(255, 51, 102, 0.3); color: #fff; }
.bm-btn.truck { border-color: rgba(16, 185, 129, 0.5); color: #6ee7b7; }
.bm-btn.truck:hover { background: rgba(16, 185, 129, 0.3); color: #fff; }
.bm-btn.safe { border-color: rgba(56, 189, 248, 0.5); color: #7dd3fc; }

.timeline-controls {
  display: flex;
  align-items: center;
  gap: 14px;
}
.play-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 6px;
  background: linear-gradient(135deg, #0284c7, #0369a1);
  border: 1px solid #38bdf8;
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 0 12px rgba(56, 189, 248, 0.3);
}
.play-btn:hover {
  background: linear-gradient(135deg, #0369a1, #075985);
  box-shadow: 0 0 16px rgba(56, 189, 248, 0.5);
}
.play-btn.playing {
  background: linear-gradient(135deg, #f59e0b, #d97706);
  border-color: #f59e0b;
}

.slider-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.timeline-slider {
  width: 100%;
  height: 6px;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.15);
  outline: none;
  cursor: pointer;
  accent-color: #00f0ff;
}
.slider-ticks {
  display: flex;
  justify-content: space-between;
  font-size: 9px;
  color: #64748b;
}
.center-tick {
  color: #00f0ff;
  font-weight: 600;
}

.speed-selector {
  display: flex;
  align-items: center;
  gap: 4px;
}
.sp-label {
  font-size: 10px;
  color: #64748b;
}
.sp-btn {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #94a3b8;
  cursor: pointer;
}
.sp-btn.active {
  background: rgba(0, 240, 255, 0.2);
  color: #00f0ff;
  border-color: #00f0ff;
  font-weight: 700;
}

/* 右侧面板 */
.right-panel {
  width: 360px;
  flex: none;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
}

/* 通用面板头 */
.panel-header {
  height: 40px;
  padding: 0 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(15, 23, 42, 0.5);
}
.panel-title {
  font-size: 12px;
  font-weight: 600;
  color: #e2e8f0;
}
.badge-live {
  font-size: 9px;
  padding: 1px 5px;
  border-radius: 3px;
  background: rgba(16, 185, 129, 0.2);
  color: #10b981;
  font-weight: 700;
}
</style>
