<template>
  <el-card class="hotstuff-table-container" shadow="hover">
    <!-- Card Header with Icon -->
    <template #header>
      <div class="card-header">
        <el-icon :size="24" class="header-icon">
          <DataAnalysis />
        </el-icon>
        <span class="header-title">Consensus Metrics Dashboard</span>
      </div>
    </template>
    
    <!-- 复杂度对比面板 - 使用 ECharts 横向柱状图 -->
    <el-card v-if="complexityComparison" class="complexity-panel" shadow="never">
      <template #header>
        <div class="panel-header">
          <el-icon :size="20">
            <TrendCharts />
          </el-icon>
          <span>Comm. Complexity Comparison</span>
        </div>
      </template>
      
      <!-- ECharts 横向柱状图 -->
      <div class="chart-container">
        <v-chart 
          :option="chartOption" 
          :autoresize="true"
          class="complexity-chart"
        />
      </div>
      
      <!-- 底部说明 -->
      <div class="comparison-note">
        <el-icon><InfoFilled /></el-icon>
        <strong>Double-Layer HotStuff advantage:</strong>
        Through group aggregation, Global Leader processes K GroupVotes
        instead of N individual votes, significantly reducing communication complexity.
      </div>
    </el-card>
    
    <!-- 消息日志面板 - 使用 Element Plus Table -->
    <el-card v-if="simulationResult" class="message-log-panel" shadow="never">
      <template #header>
        <div class="panel-header">
          <el-icon :size="20">
            <List />
          </el-icon>
          <span>Phase Message Audit Log</span>
        </div>
      </template>
      
      <el-table 
        :data="tableData" 
        stripe 
        border
        style="width: 100%"
        :header-cell-style="{ background: '#f5f7fa', fontWeight: 'bold' }"
      >
        <el-table-column prop="node" label="Node ID" width="80" align="center" />
        
        <el-table-column label="Prepare" min-width="200">
          <template #header>
            <div class="phase-header">
              Prepare
              <span class="phase-tip">Proposal / Prepare Vote</span>
            </div>
          </template>
          <template #default="{ row }">
            <div v-auto-animate class="message-list">
              <div
                v-for="msg in row.prepare"
                :key="msgKey(msg)"
                class="message-item"
              >
                <el-tag 
                  :type="getTagType(msg)" 
                  :effect="isGroupVote(msg) ? 'dark' : 'light'"
                  size="small"
                  class="message-tag"
                >
                  {{ msg.src }}→{{ formatDst(msg.dst) }}:
                  <span class="msg-label">{{ formatLabel(msg) }}</span>
                </el-tag>
                <el-tag 
                  v-if="isGroupVote(msg)" 
                  type="warning" 
                  size="small"
                  effect="dark"
                  class="group-badge"
                >
                  👑 Group Vote (Weight: {{ msg.weight || 1 }})
                </el-tag>
              </div>
            </div>
          </template>
        </el-table-column>
        
        <el-table-column label="Pre-Commit" min-width="200">
          <template #header>
            <div class="phase-header">
              Pre-Commit
              <span class="phase-tip">Pre-Commit QC / Vote</span>
            </div>
          </template>
          <template #default="{ row }">
            <div v-auto-animate class="message-list">
              <div
                v-for="msg in row.preCommit"
                :key="msgKey(msg)"
                class="message-item"
              >
                <el-tag 
                  :type="getTagType(msg)" 
                  :effect="isGroupVote(msg) ? 'dark' : 'light'"
                  size="small"
                  class="message-tag"
                >
                  {{ msg.src }}→{{ formatDst(msg.dst) }}:
                  <span class="msg-label">{{ formatLabel(msg) }}</span>
                </el-tag>
                <el-tag 
                  v-if="isGroupVote(msg)" 
                  type="warning" 
                  size="small"
                  effect="dark"
                  class="group-badge"
                >
                  👑 Group Vote (Weight: {{ msg.weight || 1 }})
                </el-tag>
              </div>
            </div>
          </template>
        </el-table-column>
        
        <el-table-column label="Commit" min-width="200">
          <template #header>
            <div class="phase-header">
              Commit
              <span class="phase-tip">Commit QC / Vote</span>
            </div>
          </template>
          <template #default="{ row }">
            <div v-auto-animate class="message-list">
              <div
                v-for="msg in row.commit"
                :key="msgKey(msg)"
                class="message-item"
              >
                <el-tag 
                  :type="getTagType(msg)" 
                  :effect="isGroupVote(msg) ? 'dark' : 'light'"
                  size="small"
                  class="message-tag"
                >
                  {{ msg.src }}→{{ formatDst(msg.dst) }}:
                  <span class="msg-label">{{ formatLabel(msg) }}</span>
                </el-tag>
                <el-tag 
                  v-if="isGroupVote(msg)" 
                  type="warning" 
                  size="small"
                  effect="dark"
                  class="group-badge"
                >
                  👑 Group Vote (Weight: {{ msg.weight || 1 }})
                </el-tag>
              </div>
            </div>
          </template>
        </el-table-column>
        
        <el-table-column label="Decide" min-width="200">
          <template #header>
            <div class="phase-header">
              Decide
              <span class="phase-tip">Decide QC</span>
            </div>
          </template>
          <template #default="{ row }">
            <div v-auto-animate class="message-list">
              <div
                v-for="msg in row.decide"
                :key="msgKey(msg)"
                class="message-item"
              >
                <el-tag 
                  :type="getTagType(msg)" 
                  :effect="isGroupVote(msg) ? 'dark' : 'light'"
                  size="small"
                  class="message-tag"
                >
                  {{ msg.src }}→{{ formatDst(msg.dst) }}:
                  <span class="msg-label">{{ formatLabel(msg) }}</span>
                </el-tag>
                <el-tag 
                  v-if="isGroupVote(msg)" 
                  type="warning" 
                  size="small"
                  effect="dark"
                  class="group-badge"
                >
                  👑 Group Vote (Weight: {{ msg.weight || 1 }})
                </el-tag>
              </div>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    
    <el-empty v-else description="No history data, please run consensus" :image-size="120" />
  </el-card>
</template>

<script setup>
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart } from 'echarts/charts'
import {
  TitleComponent,
  TooltipComponent,
  GridComponent,
  LegendComponent
} from 'echarts/components'
import VChart from 'vue-echarts'
import { 
  DataAnalysis, 
  TrendCharts, 
  List, 
  InfoFilled 
} from '@element-plus/icons-vue'

// 注册 ECharts 组件
use([
  CanvasRenderer,
  BarChart,
  TitleComponent,
  TooltipComponent,
  GridComponent,
  LegendComponent
])

const props = defineProps({
  simulationResult: { type: Object, default: null },
  nodeCount: { type: Number, default: 6 }
})

// ========== 节点列表计算 ==========
const nodes = computed(() => {
  if (!props.simulationResult || !Array.isArray(props.simulationResult.messages)) {
    return Array.from({ length: props.nodeCount }, (_, i) => i)
  }
  const maxId = props.simulationResult.messages.reduce((max, msg) => {
    const src = typeof msg.src === 'number' ? msg.src : -1
    const dst = typeof msg.dst === 'number' ? msg.dst : -1
    return Math.max(max, src, dst)
  }, -1)
  const n = Math.max(maxId + 1, props.nodeCount)
  return Array.from({ length: n }, (_, i) => i)
})

// ========== 复杂度对比数据 ==========
const complexityComparison = computed(() => {
  if (props.simulationResult?.stats?.complexity_comparison) {
    return props.simulationResult.stats.complexity_comparison
  }
  if (props.simulationResult?.complexity_comparison) {
    return props.simulationResult.complexity_comparison
  }
  return null
})

const comparisonAlgorithms = computed(() => {
  if (!complexityComparison.value) return []
  
  const comp = complexityComparison.value
  return [
    { key: 'double_hotstuff', ...comp.double_hotstuff },
    { key: 'hotstuff_pure', ...comp.hotstuff_pure },
    { key: 'pbft_multi_layer', ...comp.pbft_multi_layer },
    { key: 'pbft_pure', ...comp.pbft_pure }
  ]
})

// ========== ECharts 配置 ==========
const chartOption = computed(() => {
  if (!comparisonAlgorithms.value || comparisonAlgorithms.value.length === 0) {
    return {}
  }

  const algorithms = comparisonAlgorithms.value
  const yAxisData = algorithms.map(a => a.name)
  const theoreticalData = algorithms.map(a => a.theoretical ?? 0)
  const actualData = algorithms.map((a, index) => ({
    value: a.actual ?? 0,
    itemStyle: {
      color: getBarColor(index, a.is_current),
      borderRadius: [0, 4, 4, 0]
    }
  }))

  return {
    legend: {
      data: ['Theoretical Limit', 'Actual / Shadow'],
      top: 0,
      right: 10,
      textStyle: {
        fontSize: 12,
        color: '#606266'
      }
    },
    grid: {
      left: '15%',
      right: '30%',
      top: '12%',
      bottom: '5%'
    },
    xAxis: {
      type: 'value',
      name: 'Message Count',
      nameTextStyle: {
        fontSize: 12,
        color: '#666'
      },
      axisLabel: {
        formatter: (value) => formatNumber(value)
      }
    },
    yAxis: {
      type: 'category',
      data: yAxisData,
      axisLabel: {
        fontSize: 13,
        fontWeight: 'bold',
        formatter: (value) => {
          const algo = algorithms.find(a => a.name === value)
          return algo?.is_current ? `{current|${value}}` : value
        },
        rich: {
          current: {
            color: '#4CAF50',
            fontWeight: 'bold',
            fontSize: 14
          }
        }
      }
    },
    series: [
      {
        name: 'Theoretical Limit',
        type: 'bar',
        data: theoreticalData,
        barWidth: 14,
        itemStyle: {
          color: '#E0E0E0',
          borderRadius: [0, 4, 4, 0]
        },
        label: {
          show: true,
          position: 'right',
          formatter: (params) => formatNumber(params.value),
          fontSize: 12,
          color: '#666'
        },
        animationDuration: 1000,
        animationEasing: 'cubicOut'
      },
      {
        name: 'Actual / Shadow',
        type: 'bar',
        data: actualData,
        barWidth: 14,
        barGap: '30%',
        label: {
          show: true,
          position: 'right',
          formatter: (params) => {
            const algo = algorithms[params.dataIndex]
            return `{value|${formatNumber(params.value)}} {complexity|${algo.complexity || ''}}`
          },
          rich: {
            value: {
              fontSize: 14,
              fontWeight: 'bold',
              color: '#333'
            },
            complexity: {
              fontSize: 12,
              color: '#666',
              padding: [0, 0, 0, 8]
            }
          }
        },
        animationDuration: 1000,
        animationEasing: 'cubicOut'
      }
    ],
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: 'shadow'
      },
      formatter: (params) => {
        const dataIndex = params[0]?.dataIndex ?? 0
        const algo = algorithms[dataIndex]
        const theoretical = params.find(p => p.seriesName === 'Theoretical Limit')
        const actual = params.find(p => p.seriesName === 'Actual / Shadow')
        let html = `<div style="font-weight: bold; margin-bottom: 8px;">${algo.name}</div>`
        if (theoretical) {
          html += `<div>Theoretical: <strong>${formatNumber(theoretical.value)}</strong></div>`
        }
        if (actual) {
          html += `<div>Actual / Shadow: <strong>${formatNumber(actual.value)}</strong></div>`
        }
        html += `<div>Complexity: <code style="background: #f5f5f5; padding: 2px 6px; border-radius: 3px;">${algo.complexity}</code></div>`
        if (algo.is_current) {
          html += `<div style="color: #4CAF50; margin-top: 6px;">✅ Current system</div>`
        } else if (algo.optimization_ratio) {
          html += `<div style="color: #FF9800; margin-top: 6px;">⚡ ${algo.optimization_ratio.toFixed(1)}x optimization</div>`
        }
        return html
      }
    }
  }
})

// 获取柱状图颜色
const getBarColor = (index, isCurrent) => {
  if (isCurrent) {
    return {
      type: 'linear',
      x: 0,
      y: 0,
      x2: 1,
      y2: 0,
      colorStops: [
        { offset: 0, color: '#4CAF50' },
        { offset: 1, color: '#66BB6A' }
      ]
    }
  }
  
  const colors = [
    { start: '#2196F3', end: '#42A5F5' },  // hotstuff_pure
    { start: '#FF9800', end: '#FFB74D' },  // pbft_multi_layer
    { start: '#F44336', end: '#EF5350' }   // pbft_pure
  ]
  
  const colorIndex = index % colors.length
  return {
    type: 'linear',
    x: 0,
    y: 0,
    x2: 1,
    y2: 0,
    colorStops: [
      { offset: 0, color: colors[colorIndex].start },
      { offset: 1, color: colors[colorIndex].end }
    ]
  }
}

const formatNumber = (num) => {
  if (num === null || num === undefined) return '0'
  return num.toLocaleString('en-US')
}

// ========== Table 数据准备 ==========
const tableData = computed(() => {
  return nodes.value.map(nodeIndex => ({
    node: nodeIndex,
    prepare: getNodePhaseMessages(nodeIndex, 'prepare'),
    preCommit: getNodePhaseMessages(nodeIndex, 'pre-commit'),
    commit: getNodePhaseMessages(nodeIndex, 'commit'),
    decide: getNodePhaseMessages(nodeIndex, 'decide')
  }))
})

const getNodePhaseMessages = (nodeIndex, phase) => {
  const msgs = props.simulationResult?.messages || []
  if (!msgs || msgs.length === 0) return []

  return msgs.filter(msg => {
    if (!msg) return false
    const msgPhase = msg.phase
    const isPhaseMatch = msgPhase === phase
    const isFromNode = msg.src === nodeIndex
    const hasValidDst = msg.dst !== null && msg.dst !== undefined && 
                       (typeof msg.dst === 'number' || 
                        msg.dst === 'all' || 
                        msg.dst === 'group_leaders' || 
                        msg.dst === 'group_members')
    return isPhaseMatch && isFromNode && hasValidDst
  })
}

// ========== 消息处理函数 ==========
const msgKey = (msg) => {
  if (!msg) return 'invalid-key'
  return `${msg.src}-${msg.dst ?? 'null'}-${msg.type ?? 'msg'}-${msg.value}-${msg.weight || 0}`
}

const formatLabel = (msg) => {
  const value = msg?.value
  if (msg?.type === 'qc') {
    const weight = msg.qc?.total_weight || msg.qc?.signers?.length
    const isMultiLayer = msg.qc?.is_multi_layer
    const suffix = isMultiLayer && weight ? ` (Weight: ${weight})` : ''
    return `QC(${value})${suffix}`
  }
  if (msg?.type === 'vote') {
    return `VOTE(${value})`
  }
  if (msg?.type === 'pre_prepare' || msg?.type === 'proposal') {
    return `PROPOSAL(${value})`
  }
  return `${msg?.type ?? 'MSG'}(${value})`
}

const formatDst = (dst) => {
  if (typeof dst === 'number') return dst
  if (dst === 'all') return 'All'
  if (dst === 'group_leaders') return 'Group Leaders'
  if (dst === 'group_members') return 'Group Members'
  return dst || '?'
}

const isGroupVote = (msg) => {
  return msg?.is_group_vote === true || 
         (msg?.type === 'vote' && msg?.weight > 1) ||
         (msg?.type === 'qc' && msg?.qc?.is_multi_layer === true)
}

// Element Plus Tag 类型映射
const getTagType = (msg) => {
  if (msg?.type === 'qc') return 'success'
  if (msg?.type === 'vote') return 'warning'
  if (msg?.type === 'pre_prepare' || msg?.type === 'proposal') return 'primary'
  return 'info'
}
</script>

<style scoped>
.hotstuff-table-container {
  width: 100%;
  max-width: 1200px;
  margin: 0 auto;
}

/* Card Header 样式 */
.card-header {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 18px;
  font-weight: bold;
  color: #303133;
}

.header-icon {
  color: #409eff;
}

.header-title {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

/* 复杂度对比面板 */
.complexity-panel {
  margin-bottom: 24px;
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.05) 0%, rgba(118, 75, 162, 0.05) 100%);
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: bold;
  color: #606266;
}

/* ECharts 容器 */
.chart-container {
  width: 100%;
  height: 400px;
  margin: 20px 0;
}

.complexity-chart {
  width: 100%;
  height: 100%;
}

/* 底部说明 */
.comparison-note {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px;
  background: #f0f9ff;
  border-left: 4px solid #409eff;
  border-radius: 4px;
  font-size: 14px;
  color: #606266;
  line-height: 1.6;
  margin-top: 16px;
}

.comparison-note strong {
  color: #303133;
}

/* 消息日志面板 */
.message-log-panel {
  margin-top: 24px;
}

/* Phase Header */
.phase-header {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.phase-tip {
  font-size: 11px;
  color: #909399;
  font-weight: normal;
}

/* 消息列表 */
.message-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 24px;
}

.message-item {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.message-tag {
  cursor: default;
  user-select: none;
  transition: all 0.3s ease;
}

.message-tag:hover {
  transform: translateX(2px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}

.msg-label {
  font-weight: 600;
}

.group-badge {
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.8;
  }
}

/* 响应式调整 */
@media (max-width: 768px) {
  .chart-container {
    height: 250px;
  }
  
  .card-header {
    font-size: 16px;
  }
  
  .panel-header {
    font-size: 14px;
  }
}
</style>
