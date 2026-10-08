<template>
  <div class="task-panel-card">
    <div class="card-header">
      <div class="header-left">
        <span class="card-title">调度车队与路径规划</span>
        <span class="status-tag" :class="activeTruckCount > 0 ? 'active' : 'idle'">
          {{ activeTruckCount > 0 ? `${activeTruckCount} 车作业中` : '待命中' }}
        </span>
      </div>
      <button class="minimal-btn" :disabled="loading" @click="$emit('refresh')">
        {{ loading ? '求解中…' : 'CVRP 规划' }}
      </button>
    </div>

    <div class="card-body">
      <!-- 动态演化专车状态 -->
      <div v-if="trucks && trucks.length" class="fleet-group">
        <div class="group-title">实时出勤车辆 (削峰填谷)</div>
        <div v-for="t in trucks" :key="t.id" class="truck-item">
          <div class="truck-head">
            <span class="truck-id-badge">{{ t.id }}号车</span>
            <span class="truck-name">{{ t.name }}</span>
            <span class="truck-state-chip" :class="t.status">{{ t.status_text }}</span>
          </div>

          <div class="truck-desc">{{ t.action }}</div>

          <div class="truck-bar-wrap">
            <div class="bar-meta">
              <span>装载负荷</span>
              <strong>{{ t.load }} / {{ t.capacity }} 辆</strong>
            </div>
            <div class="bar-bg">
              <div
                class="bar-active"
                :style="{ width: Math.min(100, Math.round((t.load / t.capacity) * 100)) + '%' }"
              ></div>
            </div>
          </div>
        </div>
      </div>

      <!-- CVRP 求解方案 -->
      <div v-if="dispatch && dispatch.tasks && dispatch.tasks.length" class="cvrp-group">
        <div class="group-title">
          <span>CVRP 最优路径方案</span>
          <span class="dist-num">{{ (dispatch.total_distance / 1000).toFixed(2) }} km</span>
        </div>

        <!-- 求解器对比（改进遗传算法 vs OR-Tools 对照），无该字段则不渲染 -->
        <div v-if="solverCompareText" class="solver-compare">
          {{ solverCompareText }}
        </div>

        <div class="cvrp-list">
          <div v-for="task in dispatch.tasks" :key="task.vehicle_id" class="cvrp-item">
            <div class="cvrp-info">
              <span class="v-num">车 {{ task.vehicle_id }}</span>
              <span class="v-route-desc">{{ task.distance_km }} km · 规划装运 {{ task.load }}辆</span>
            </div>
            <div class="cvrp-tags">
              <span
                v-for="(s, i) in task.stops"
                :key="i"
                class="stop-pill"
                :class="s.op === 'pickup' ? 'pickup' : 'delivery'"
              >
                {{ s.op === 'pickup' ? '削峰提车' : '补缺投放' }} {{ s.qty }}辆
              </span>
            </div>
          </div>
        </div>
      </div>

      <div v-if="(!trucks || !trucks.length) && (!dispatch || !dispatch.tasks || !dispatch.tasks.length)" class="empty-state">
        系统正在依据各热点容量阈值持续监控失衡态势…
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  dispatch: Object,
  trucks: Array,
  loading: Boolean,
})

defineEmits(['refresh'])

const activeTruckCount = computed(() => {
  if (!props.trucks) return 0
  return props.trucks.filter((t) => t.status && t.status !== 'standby' && t.status !== 'completed').length
})

// 求解器对比文案：例如「GA 1.22 km / 38 ms · OR-Tools 1.18 km / 210 ms」
const solverCompareText = computed(() => {
  const cmp = props.dispatch?.solver_comparison
  if (!cmp) return ''
  const label = { ga: 'GA', ortools: 'OR-Tools' }
  const parts = []
  for (const key of ['ga', 'ortools']) {
    const item = cmp[key]
    if (!item || item.total_distance == null) continue
    const km = (item.total_distance / 1000).toFixed(2)
    const ms = item.elapsed_ms != null ? ` / ${Math.round(item.elapsed_ms)} ms` : ''
    parts.push(`${label[key]} ${km} km${ms}`)
  }
  return parts.length ? `求解对比 · ${parts.join(' · ')}` : ''
})
</script>

<style scoped>
.task-panel-card {
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
.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.card-title {
  font-size: 12px;
  font-weight: 600;
  color: #0f172a;
}
.status-tag {
  font-size: 10px;
  font-weight: 500;
  padding: 1px 6px;
  border-radius: 4px;
}
.status-tag.idle {
  background: #f1f5f9;
  color: #64748b;
}
.status-tag.active {
  background: #ecfdf5;
  color: #059669;
}

.card-body {
  flex: 1;
  overflow-y: auto;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 260px;
}

.group-title {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  color: #64748b;
  letter-spacing: 0.5px;
  margin-bottom: 6px;
}
.dist-num {
  font-family: monospace;
  color: #0f172a;
}

/* 求解器对比小字 */
.solver-compare {
  font-size: 9px;
  font-family: monospace;
  color: #64748b;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  padding: 3px 6px;
  margin-bottom: 6px;
  letter-spacing: 0.2px;
}

/* 专车条目 */
.truck-item {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 7px 10px;
  margin-bottom: 6px;
}
.truck-head {
  display: flex;
  align-items: center;
  gap: 6px;
}
.truck-id-badge {
  font-size: 9px;
  background: #0f172a;
  color: #ffffff;
  padding: 1px 4px;
  border-radius: 3px;
  font-weight: 600;
}
.truck-name {
  font-size: 11px;
  font-weight: 600;
  color: #1e293b;
}
.truck-state-chip {
  margin-left: auto;
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
  font-weight: 500;
}
.truck-state-chip.standby { background: #f1f5f9; color: #64748b; }
.truck-state-chip.loading { background: #fff7ed; color: #ea580c; }
.truck-state-chip.hauling { background: #eff6ff; color: #2563eb; }
.truck-state-chip.unloading { background: #ecfdf5; color: #059669; }
.truck-state-chip.completed { background: #faf5ff; color: #7c3aed; }

.truck-desc {
  font-size: 10px;
  color: #64748b;
  margin: 4px 0;
  line-height: 1.3;
}

.truck-bar-wrap {
  margin-top: 3px;
}
.bar-meta {
  display: flex;
  justify-content: space-between;
  font-size: 9px;
  color: #64748b;
  margin-bottom: 2px;
}
.bar-meta strong {
  color: #0f172a;
}
.bar-bg {
  width: 100%;
  height: 4px;
  border-radius: 2px;
  background: #e2e8f0;
  overflow: hidden;
}
.bar-active {
  height: 100%;
  border-radius: 2px;
  background: #0f172a;
  transition: width 0.25s ease;
}

/* CVRP 列表条目 */
.cvrp-item {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 6px 9px;
  margin-bottom: 5px;
}
.cvrp-info {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  margin-bottom: 4px;
}
.v-num { font-weight: 600; color: #0f172a; }
.v-route-desc { color: #64748b; }
.cvrp-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.stop-pill {
  font-size: 9px;
  padding: 1px 5px;
  border-radius: 3px;
}
.stop-pill.pickup {
  background: #ffe4e6;
  color: #be123c;
}
.stop-pill.delivery {
  background: #dcfce7;
  color: #15803d;
}

.empty-state {
  padding: 24px;
  text-align: center;
  color: #94a3b8;
  font-size: 11px;
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
