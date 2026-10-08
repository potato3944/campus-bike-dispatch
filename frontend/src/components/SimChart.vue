<template>
  <div class="sim-chart-card">
    <div class="card-header">
      <div class="header-segment">
        <button class="seg-btn" :class="{ active: tab === 'trend' }" @click="tab = 'trend'">
          实时聚集演化趋势
        </button>
        <button class="seg-btn" :class="{ active: tab === 'sim' }" @click="tab = 'sim'">
          调度策略对比实验
        </button>
      </div>
      <button v-if="tab === 'sim'" class="minimal-btn" :disabled="loading" @click="$emit('run')">
        {{ loading ? '仿真计算中…' : '执行 SimPy 仿真' }}
      </button>
    </div>

    <!-- 趋势曲线模式 -->
    <div v-show="tab === 'trend'" class="chart-content">
      <div ref="trendChartEl" class="chart-body"></div>
      <div class="chart-caption-row">
        <span class="caption-item red"><i class="sq"></i>教学区存车量 (聚集暴增)</span>
        <span class="caption-item blue"><i class="sq"></i>宿舍区存车量 (潮汐排空与回补)</span>
        <span class="caption-item gray"><i class="sq"></i>在途骑行中</span>
      </div>
    </div>

    <!-- 仿真对比模式 -->
    <div v-show="tab === 'sim'" class="chart-content">
      <div ref="simChartEl" class="chart-body"></div>
      <div v-if="results && results.length" class="sim-data-table-wrap">
        <table class="sim-data-table">
          <thead>
            <tr>
              <th class="text-left">调度策略</th>
              <th>供需匹配率</th>
              <th>平均等待</th>
              <th>任务数</th>
              <th>综合成本</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in results" :key="r.strategy">
              <td class="text-left font-medium">{{ strategyName(r.strategy) }}</td>
              <td class="text-emerald">{{ (r.match_rate * 100).toFixed(1) }}%</td>
              <td>{{ r.avg_wait_min }} min</td>
              <td>{{ r.dispatch_tasks }} 次</td>
              <td class="font-mono">¥{{ r.total_cost }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else-if="loading" class="empty-state loading-state">
        <span class="spinner-dot"></span>
        首次仿真约需 30~60 秒，请稍候…（结果会被缓存，重复调用秒回）
      </div>
      <div v-else class="empty-state">
        点击右上角「执行 SimPy 仿真」评估无调度 vs 阈值触发 vs 预测调度的算法对比指标
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

const strategyName = (s) => ({ none: '无调度 (自然放任)', threshold: '阈值触发调度', predictive: '预测性调度' }[s] || s)

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
      backgroundColor: 'rgba(15, 23, 42, 0.95)',
      borderColor: '#334155',
      textStyle: { color: '#f8fafc', fontSize: 11 },
      padding: [6, 10],
    },
    grid: { left: 34, right: 14, top: 18, bottom: 22 },
    xAxis: {
      type: 'category',
      data: times,
      axisLine: { lineStyle: { color: '#cbd5e1' } },
      axisTick: { show: false },
      axisLabel: { color: '#64748b', fontSize: 10, interval: Math.floor(times.length / 5) },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: '#f1f5f9' } },
      axisLabel: { color: '#64748b', fontSize: 10 },
    },
    series: [
      {
        name: '教学区存车量',
        type: 'line',
        smooth: true,
        data: teaching,
        lineStyle: { width: 2.2, color: '#e11d48' },
        itemStyle: { color: '#e11d48' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(225, 29, 72, 0.18)' },
            { offset: 1, color: 'rgba(225, 29, 72, 0.01)' },
          ]),
        },
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: '#0f172a', width: 1.5, type: 'dashed' },
          data: [{ xAxis: curTime, label: { show: true, formatter: '当前演化', color: '#0f172a', fontSize: 9 } }],
        },
      },
      {
        name: '宿舍区存车量',
        type: 'line',
        smooth: true,
        data: dorm,
        lineStyle: { width: 2, color: '#0284c7' },
        itemStyle: { color: '#0284c7' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(2, 132, 199, 0.12)' },
            { offset: 1, color: 'rgba(2, 132, 199, 0.01)' },
          ]),
        },
      },
      {
        name: '在途骑行中',
        type: 'line',
        smooth: true,
        data: moving,
        lineStyle: { width: 1.5, color: '#94a3b8', type: 'dotted' },
        itemStyle: { color: '#94a3b8' },
      },
    ],
  }

  trendChart.setOption(option)
}

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
      backgroundColor: 'rgba(15, 23, 42, 0.95)',
      textStyle: { color: '#f8fafc', fontSize: 11 },
    },
    legend: {
      data: ['供需匹配率 (%)', '综合成本 (元)'],
      textStyle: { color: '#475569', fontSize: 10 },
      top: 0,
    },
    grid: { left: 34, right: 34, top: 28, bottom: 22 },
    xAxis: {
      type: 'category',
      data: names,
      axisLine: { lineStyle: { color: '#cbd5e1' } },
      axisLabel: { color: '#475569', fontSize: 10 },
    },
    yAxis: [
      {
        type: 'value',
        max: 100,
        splitLine: { lineStyle: { color: '#f1f5f9' } },
        axisLabel: { color: '#64748b', fontSize: 9 },
      },
      {
        type: 'value',
        splitLine: { show: false },
        axisLabel: { color: '#64748b', fontSize: 9 },
      },
    ],
    series: [
      {
        name: '供需匹配率 (%)',
        type: 'bar',
        data: matchRates,
        barWidth: 18,
        itemStyle: { color: '#0f172a', borderRadius: [3, 3, 0, 0] },
      },
      {
        name: '综合成本 (元)',
        type: 'line',
        yAxisIndex: 1,
        data: costs,
        lineStyle: { width: 2, color: '#ea580c' },
        itemStyle: { color: '#ea580c' },
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
.sim-chart-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}
.card-header {
  height: 42px;
  padding: 0 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #f1f5f9;
  background: #ffffff;
}
.header-segment {
  display: flex;
  background: #f1f5f9;
  padding: 2px;
  border-radius: 6px;
  gap: 2px;
}
.seg-btn {
  padding: 3px 9px;
  font-size: 11px;
  font-weight: 500;
  border: none;
  background: transparent;
  color: #64748b;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.seg-btn:hover {
  color: #0f172a;
}
.seg-btn.active {
  background: #ffffff;
  color: #0f172a;
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
}

.chart-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 200px;
  padding: 10px 12px;
}
.chart-body {
  width: 100%;
  height: 160px;
}
.chart-caption-row {
  display: flex;
  justify-content: center;
  gap: 16px;
  margin-top: 4px;
}
.caption-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 10px;
  color: #64748b;
}
.sq { width: 7px; height: 7px; border-radius: 2px; display: inline-block; }
.red .sq { background: #e11d48; }
.blue .sq { background: #0284c7; }
.gray .sq { background: #94a3b8; }

.sim-data-table-wrap {
  margin-top: 8px;
  overflow-x: auto;
}
.sim-data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
  color: #334155;
}
.sim-data-table th, .sim-data-table td {
  padding: 5px 6px;
  text-align: center;
  border-bottom: 1px solid #f1f5f9;
}
.sim-data-table th {
  color: #64748b;
  font-weight: 500;
  background: #f8fafc;
}
.text-left { text-align: left; }
.font-medium { font-weight: 500; }
.text-emerald { color: #059669; font-weight: 600; }
.font-mono { font-family: monospace; font-size: 10px; }

.empty-state {
  padding: 24px;
  text-align: center;
  color: #94a3b8;
  font-size: 11px;
  line-height: 1.6;
}

.loading-state {
  color: #64748b;
}
.spinner-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  margin-right: 6px;
  border-radius: 50%;
  background: #0f172a;
  animation: pulse-dot 1s ease-in-out infinite;
}
@keyframes pulse-dot {
  0%, 100% { opacity: 0.25; transform: scale(0.85); }
  50% { opacity: 1; transform: scale(1.1); }
}

.minimal-btn {
  padding: 4px 8px;
  font-size: 11px;
  font-weight: 500;
  border-radius: 4px;
  background: #0f172a;
  color: #ffffff;
  border: none;
  cursor: pointer;
  transition: all 0.15s;
}
.minimal-btn:hover:not(:disabled) {
  background: #334155;
}
.minimal-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
