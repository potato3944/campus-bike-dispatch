<template>
  <div class="task-panel panel">
    <div class="panel-header">
      <div class="header-left">
        <span class="panel-title">🚚 智能调度车队与路径</span>
        <span class="status-pill" :class="activeTruckCount > 0 ? 'running' : 'idle'">
          {{ activeTruckCount > 0 ? `${activeTruckCount} 辆专车作业中` : '待命' }}
        </span>
      </div>
      <button class="btn btn-primary btn-sm" :disabled="loading" @click="$emit('refresh')">
        {{ loading ? 'OR-Tools 求解中…' : 'CVRP 路径规划' }}
      </button>
    </div>

    <div class="panel-body">
      <!-- 动态演化模式下的专车卡片 -->
      <div v-if="trucks && trucks.length" class="fleet-section">
        <div class="section-title">实时出勤专车状态 (动态削峰)</div>
        <div v-for="t in trucks" :key="t.id" class="truck-card" :class="t.status">
          <div class="truck-top">
            <div class="t-name">
              <span class="t-badge">{{ t.id }}号车</span>
              <strong>{{ t.name }}</strong>
            </div>
            <span class="t-state" :class="t.status">{{ t.status_text }}</span>
          </div>

          <div class="t-action">{{ t.action }}</div>

          <div class="load-bar-wrap">
            <div class="load-txt">
              <span>运载装载量</span>
              <strong :class="{ full: t.load >= t.capacity }">{{ t.load }} / {{ t.capacity }} 辆</strong>
            </div>
            <div class="bar-track">
              <div
                class="bar-fill"
                :style="{ width: Math.min(100, Math.round((t.load / t.capacity) * 100)) + '%' }"
              ></div>
            </div>
          </div>
        </div>
      </div>

      <!-- 静态 CVRP 方案列表 -->
      <div v-if="dispatch && dispatch.tasks && dispatch.tasks.length" class="cvrp-section">
        <div class="section-title">
          <span>CVRP 最优调度规划方案</span>
          <span class="cvrp-dist">总里程: {{ (dispatch.total_distance / 1000).toFixed(2) }} km</span>
        </div>
        <div class="task-list">
          <div v-for="task in dispatch.tasks" :key="task.vehicle_id" class="cvrp-card">
            <div class="cvrp-head">
              <span class="v-tag">车辆 {{ task.vehicle_id }}</span>
              <span class="v-meta">{{ task.distance_km }} km · 规划装运 {{ task.load }}辆</span>
            </div>
            <div class="cvrp-stops">
              <span
                v-for="(s, i) in task.stops"
                :key="i"
                class="stop-badge"
                :class="s.op === 'pickup' ? 'pickup' : 'delivery'"
              >
                {{ s.op === 'pickup' ? '⬆️ 削峰拉走' : '⬇️ 补缺投放' }} {{ s.qty }}辆
              </span>
            </div>
          </div>
        </div>
      </div>

      <div v-if="(!trucks || !trucks.length) && (!dispatch || !dispatch.tasks || !dispatch.tasks.length)" class="empty">
        暂无活跃调度任务，系统正在根据区域失衡阈值持续监控…
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
</script>

<style scoped>
.task-panel {
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
.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.panel-title {
  font-size: 13px;
  font-weight: 600;
  color: #e2e8f0;
}
.status-pill {
  font-size: 10px;
  padding: 2px 7px;
  border-radius: 10px;
  background: rgba(100, 116, 139, 0.2);
  color: #94a3b8;
  border: 1px solid rgba(148, 163, 184, 0.25);
}
.status-pill.running {
  background: rgba(16, 185, 129, 0.2);
  color: #10b981;
  border-color: rgba(16, 185, 129, 0.4);
  box-shadow: 0 0 8px rgba(16, 185, 129, 0.25);
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 280px;
}

.section-title {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  font-weight: 600;
  color: #94a3b8;
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.cvrp-dist {
  color: #00f0ff;
}

/* 专车卡片 */
.truck-card {
  background: rgba(15, 23, 42, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 6px;
  transition: all 0.2s ease;
}
.truck-card.loading, .truck-card.hauling, .truck-card.unloading {
  border-color: rgba(16, 185, 129, 0.4);
  box-shadow: 0 0 12px rgba(16, 185, 129, 0.15);
}
.truck-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.t-name {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #f1f5f9;
  font-size: 12px;
}
.t-badge {
  font-size: 9px;
  background: rgba(0, 240, 255, 0.2);
  color: #00f0ff;
  padding: 1px 4px;
  border-radius: 3px;
  font-weight: 700;
}
.t-state {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}
.t-state.standby { background: rgba(100, 116, 139, 0.2); color: #94a3b8; }
.t-state.loading { background: rgba(245, 158, 11, 0.2); color: #f59e0b; }
.t-state.hauling { background: rgba(56, 189, 248, 0.2); color: #38bdf8; }
.t-state.unloading { background: rgba(16, 185, 129, 0.2); color: #10b981; }
.t-state.completed { background: rgba(168, 85, 247, 0.2); color: #a855f7; }

.t-action {
  font-size: 11px;
  color: #cbd5e1;
  margin: 5px 0;
  line-height: 1.3;
}

.load-bar-wrap {
  margin-top: 4px;
}
.load-txt {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: #94a3b8;
  margin-bottom: 2px;
}
.load-txt strong { color: #00f0ff; }
.load-txt strong.full { color: #f59e0b; }
.bar-track {
  width: 100%;
  height: 5px;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.08);
  overflow: hidden;
}
.bar-fill {
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(to right, #00f0ff, #10b981);
  transition: width 0.3s ease;
}

/* CVRP 卡片 */
.cvrp-card {
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 6px;
  padding: 7px 10px;
  margin-bottom: 6px;
}
.cvrp-head {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  margin-bottom: 5px;
}
.v-tag { color: #00f0ff; font-weight: 600; }
.v-meta { color: #94a3b8; }
.cvrp-stops {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.stop-badge {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 3px;
  border: 1px solid transparent;
}
.stop-badge.pickup {
  background: rgba(255, 51, 102, 0.15);
  color: #ff3366;
  border-color: rgba(255, 51, 102, 0.3);
}
.stop-badge.delivery {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
  border-color: rgba(16, 185, 129, 0.3);
}

.empty {
  padding: 24px;
  text-align: center;
  color: #64748b;
  font-size: 12px;
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
