<template>
  <div class="sim-chart-panel panel">
    <div class="panel-header">
      <div class="header-tabs">
        <button class="tab-btn" :class="{ active: tab === 'trend' }" @click="tab = 'trend'">
          📈 实时聚集趋势
        </button>
        <button class="tab-btn" :class="{ active: tab === 'sim' }" @click="tab = 'sim'">
          📊 调度策略对比
        </button>
      </div>
      <button v-if="tab === 'sim'" class="btn btn-primary btn-sm" :disabled="loading" @click="$emit('run')">
        {{ loading ? '仿真求解中…' : '运行 SimPy 仿真' }}
      </button>
    </div>

    <!-- 趋势图模式：直观展示单车聚集与清退过程 -->
    <div v-show="tab === 'trend'" class="trend-container">
      <div ref="trendChartEl" class="chart-box"></div>
      <div class="trend-legend-bar">
        <span class="lg-tag red"><i class="sq"></i>教学区存车量 (聚集暴增)</span>
        <span class="lg-tag blue"><i class="sq"></i>宿舍区存车量 (骤降与回补)</span>
        <span class="lg-tag orange"><i class="sq"></i>骑行流动中</span>
      </div>
    </div>

    <!-- 仿真对比模式 -->
    <div v-show="tab === 'sim'" class="sim-container">
      <div ref="simChartEl" class="chart-box"></div>
      <div v-if="results && results.length" class="sim-table-wrap">
        <table class="sim-table">
          <thead>
            <tr>
              <th>调度策略</th>
              <th>供需匹配率</th>
              <th>平均等待</th>
              <th>任务数</th>
              <th>总成本</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in results" :key="r.strategy">
              <td class="st-name">{{ strategyName(r.strategy) }}</td>
              <td class="match">{{ (r.match_rate * 100).toFixed(1) }}%</td>
              <td>{{ r.avg_wait_min }} min</td>
              <td>{{ r.dispatch_tasks }} 次</td>
              <td class="cost">¥{{ r.total_cost }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty-hint">
        点击右上角「运行 SimPy 仿真」对比无调度 vs 阈值调度 vs 预测调度的算法表现
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  results: Array,
  loading: Boolean,
  frames: Array,
  currentStep: Number,
})

defineEmits(['run'])

const tab = ref('trend')
const trendChartEl = ref(null)
const simChartEl = ref(null)
let trendChart = null
let simChart = null

const strategyName = (s) => ({ none: '无调度 (自然放任)', threshold: '阈值触发调度', predictive: '预测性智能调度' }[s] || s)

/* 渲染实时聚集演化曲线 */
function renderTrendChart() {
  if (!trendChartEl.value) return
  if (!trendChart) {
    trendChart = echarts.init(trendChartEl.value)
  }

  const frames = props.frames || []
  if (!frames.length) {
    trendChart.clear()
    return
  }

  const times = frames.map((f) => f.time)
  const teaching = frames.map((f) => f.teaching_total)
  const dorm = frames.map((f) => f.dorm_total)
  const moving = frames.map((f) => f.active_moving)

  const curTime = frames[props.currentStep]?.time || times[0]

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(15, 23, 42, 0.92)',
      borderColor: 'rgba(0, 240, 255, 0.3)',
      textStyle: { color: '#e2e8f0', fontSize: 12 },
    },
    grid: { left: 40, right: 20, top: 20, bottom: 25 },
    xAxis: {
      type: 'category',
      data: times,
      axisLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.15)' } },
      axisLabel: { color: '#94a3b8', fontSize: 10, interval: Math.floor(times.length / 6) },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.06)' } },
      axisLabel: { color: '#94a3b8', fontSize: 10 },
    },
    series: [
      {
        name: '教学区存车量 (聚集暴增)',
        type: 'line',
        smooth: true,
        data: teaching,
        lineStyle: { width: 2.5, color: '#ff3366' },
        itemStyle: { color: '#ff3366' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(255, 51, 102, 0.45)' },
            { offset: 1, color: 'rgba(255, 51, 102, 0.02)' },
          ]),
        },
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: '#00f0ff', width: 2, type: 'dashed' },
          data: [{ xAxis: curTime, label: { show: true, formatter: '当前演化时刻', color: '#00f0ff' } }],
        },
      },
      {
        name: '宿舍区存车量',
        type: 'line',
        smooth: true,
        data: dorm,
        lineStyle: { width: 2, color: '#38bdf8' },
        itemStyle: { color: '#38bdf8' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(56, 189, 248, 0.35)' },
            { offset: 1, color: 'rgba(56, 189, 248, 0.02)' },
          ]),
        },
      },
      {
        name: '骑行流动中',
        type: 'line',
        smooth: true,
        data: moving,
        lineStyle: { width: 1.5, color: '#f59e0b', type: 'dashed' },
        itemStyle: { color: '#f59e0b' },
      },
    ],
  }

  trendChart.setOption(option)
}

/* 渲染仿真对比柱状/折线图 */
function renderSimChart() {
  if (!simChartEl.value) return
  if (!simChart) {
    simChart = echarts.init(simChartEl.value)
  }

  const rs = props.results || []
  if (!rs.length) {
    simChart.clear()
    return
  }

  const names = rs.map((r) => strategyName(r.strategy))
  const matchRates = rs.map((r) => (r.match_rate * 100).toFixed(1))
  const costs = rs.map((r) => r.total_cost)

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(15, 23, 42, 0.92)',
      borderColor: 'rgba(0, 240, 255, 0.3)',
      textStyle: { color: '#e2e8f0', fontSize: 12 },
    },
    legend: {
      data: ['供需匹配率 (%)', '综合成本 (元)'],
      textStyle: { color: '#94a3b8', fontSize: 11 },
      top: 0,
    },
    grid: { left: 45, right: 45, top: 32, bottom: 25 },
    xAxis: {
      type: 'category',
      data: names,
      axisLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.15)' } },
      axisLabel: { color: '#cbd5e1', fontSize: 10 },
    },
    yAxis: [
      {
        type: 'value',
        name: '匹配率%',
        max: 100,
        splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.06)' } },
        axisLabel: { color: '#94a3b8', fontSize: 10 },
      },
      {
        type: 'value',
        name: '成本¥',
        splitLine: { show: false },
        axisLabel: { color: '#94a3b8', fontSize: 10 },
      },
    ],
    series: [
      {
        name: '供需匹配率 (%)',
        type: 'bar',
        data: matchRates,
        barWidth: 22,
        itemStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: '#00f0ff' },
            { offset: 1, color: '#0284c7' },
          ]),
          borderRadius: [4, 4, 0, 0],
        },
      },
      {
        name: '综合成本 (元)',
        type: 'line',
        yAxisIndex: 1,
        data: costs,
        lineStyle: { width: 2.5, color: '#f59e0b' },
        itemStyle: { color: '#f59e0b' },
      },
    ],
  }

  simChart.setOption(option)
}

function resizeCharts() {
  trendChart && trendChart.resize()
  simChart && simChart.resize()
}

watch(tab, (t) => {
  nextTick(() => {
    resizeCharts()
    if (t === 'trend') renderTrendChart()
    else renderSimChart()
  })
})

watch(() => props.frames, () => renderTrendChart(), { deep: true })
watch(() => props.currentStep, () => renderTrendChart())
watch(() => props.results, () => renderSimChart(), { deep: true })

onMounted(() => {
  renderTrendChart()
  window.addEventListener('resize', resizeCharts)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeCharts)
  trendChart && trendChart.dispose()
  simChart && simChart.dispose()
})
</script>

<style scoped>
.sim-chart-panel {
  background: rgba(14, 20, 36, 0.82);
  border: 1px solid rgba(0, 240, 255, 0.18);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.panel-header {
  height: 44px;
  padding: 0 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(15, 23, 42, 0.5);
}
.header-tabs {
  display: flex;
  gap: 6px;
}
.tab-btn {
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 500;
  border: 1px solid transparent;
  background: transparent;
  color: #94a3b8;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
}
.tab-btn:hover {
  color: #00f0ff;
}
.tab-btn.active {
  background: rgba(0, 240, 255, 0.15);
  border-color: rgba(0, 240, 255, 0.4);
  color: #00f0ff;
  font-weight: 600;
}

.trend-container, .sim-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 220px;
  padding: 10px 12px;
}
.chart-box {
  width: 100%;
  height: 180px;
}
.trend-legend-bar {
  display: flex;
  justify-content: center;
  gap: 14px;
  margin-top: 6px;
}
.lg-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: #cbd5e1;
}
.sq { width: 8px; height: 8px; border-radius: 2px; display: inline-block; }
.red .sq { background: #ff3366; }
.blue .sq { background: #38bdf8; }
.orange .sq { background: #f59e0b; }

.sim-table-wrap {
  margin-top: 8px;
  overflow-x: auto;
}
.sim-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
  color: #cbd5e1;
}
.sim-table th, .sim-table td {
  padding: 6px 8px;
  text-align: center;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.sim-table th {
  color: #94a3b8;
  font-weight: 600;
  background: rgba(15, 23, 42, 0.6);
}
.st-name { text-align: left; font-weight: 600; color: #f8fafc; }
.match { color: #10b981; font-weight: 600; }
.cost { color: #f59e0b; }

.empty-hint {
  padding: 24px;
  text-align: center;
  color: #64748b;
  font-size: 12px;
  line-height: 1.6;
}

.btn-sm {
  padding: 4px 10px;
  font-size: 11px;
  border-radius: 4px;
  background: #0284c7;
  color: #fff;
  border: 1px solid #38bdf8;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-sm:hover:not(:disabled) {
  background: #0369a1;
  box-shadow: 0 0 10px rgba(56, 189, 248, 0.4);
}
.btn-sm:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
