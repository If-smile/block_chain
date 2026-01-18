<template>
  <div class="hotstuff-table-container">
    <h2>HotStuff Stages</h2>
    
    <!-- 4种共识算法通信复杂度对比面板 -->
    <div v-if="complexityComparison" class="complexity-panel">
      <h3>📊 共识算法通信复杂度对比</h3>
      <div class="comparison-table">
        <div 
          v-for="(algo, key) in comparisonAlgorithms" 
          :key="key"
          class="algorithm-card"
          :class="{ 'current-system': algo.is_current }"
        >
          <div class="algorithm-header">
            <span class="algorithm-name">{{ algo.name }}</span>
            <span v-if="algo.is_current" class="current-badge">当前系统</span>
            <span v-else-if="algo.optimization_ratio" class="optimization-badge">
              {{ algo.optimization_ratio.toFixed(1) }}x 优化
            </span>
          </div>
          <div class="algorithm-stats">
            <div class="stat-row">
              <span class="stat-label">消息数量:</span>
              <span class="stat-value">{{ formatNumber(algo.messages) }}</span>
            </div>
            <div class="stat-row">
              <span class="stat-label">复杂度:</span>
              <span class="stat-value complexity">{{ algo.complexity }}</span>
            </div>
          </div>
          <!-- 进度条可视化 -->
          <div class="progress-container">
            <div class="progress-bar-wrapper">
              <div 
                class="progress-bar"
                :class="getProgressBarClass(key)"
                :style="{ width: getProgressWidth(algo.messages) + '%' }"
              >
                <span class="progress-text">{{ formatNumber(algo.messages) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div class="comparison-note">
        💡 <strong>双层 HotStuff 优势</strong>：通过分组聚合，Global Leader 只需处理 K 个 GroupVote，
        而不是 N 个单独投票，通信复杂度显著降低
      </div>
    </div>
    
    <table v-if="simulationResult" class="hotstuff-table">
      <thead>
        <tr>
          <th>Node</th>
          <th>Prepare<br /><span class="col-tip">Proposal / Prepare Vote</span></th>
          <th>Pre-Commit<br /><span class="col-tip">Pre-Commit QC / Vote</span></th>
          <th>Commit<br /><span class="col-tip">Commit QC / Vote</span></th>
          <th>Decide<br /><span class="col-tip">Decide QC</span></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="node in nodes" :key="node">
          <td>{{ node }}</td>
          <!-- Prepare column -->
          <td>
            <div
              v-for="msg in getNodePhaseMessages(node, 'prepare')"
              :key="msgKey(msg)"
              class="msg-line"
              :class="[getMsgClass(msg), { 'group-vote': isGroupVote(msg) }]"
            >
              {{ msg.src }}→{{ formatDst(msg.dst) }}:
              <span class="msg-label">{{ formatLabel(msg) }}</span>
              <span v-if="isGroupVote(msg)" class="group-vote-badge">👑 Group Vote (Weight: {{ msg.weight || 1 }})</span>
            </div>
          </td>
          <!-- Pre-Commit column -->
          <td>
            <div
              v-for="msg in getNodePhaseMessages(node, 'pre-commit')"
              :key="msgKey(msg)"
              class="msg-line"
              :class="[getMsgClass(msg), { 'group-vote': isGroupVote(msg) }]"
            >
              {{ msg.src }}→{{ formatDst(msg.dst) }}:
              <span class="msg-label">{{ formatLabel(msg) }}</span>
              <span v-if="isGroupVote(msg)" class="group-vote-badge">👑 Group Vote (Weight: {{ msg.weight || 1 }})</span>
            </div>
          </td>
          <!-- Commit column -->
          <td>
            <div
              v-for="msg in getNodePhaseMessages(node, 'commit')"
              :key="msgKey(msg)"
              class="msg-line"
              :class="[getMsgClass(msg), { 'group-vote': isGroupVote(msg) }]"
            >
              {{ msg.src }}→{{ formatDst(msg.dst) }}:
              <span class="msg-label">{{ formatLabel(msg) }}</span>
              <span v-if="isGroupVote(msg)" class="group-vote-badge">👑 Group Vote (Weight: {{ msg.weight || 1 }})</span>
            </div>
          </td>
          <!-- Decide column -->
          <td>
            <div
              v-for="msg in getNodePhaseMessages(node, 'decide')"
              :key="msgKey(msg)"
              class="msg-line"
              :class="[getMsgClass(msg), { 'group-vote': isGroupVote(msg) }]"
            >
              {{ msg.src }}→{{ formatDst(msg.dst) }}:
              <span class="msg-label">{{ formatLabel(msg) }}</span>
              <span v-if="isGroupVote(msg)" class="group-vote-badge">👑 Group Vote (Weight: {{ msg.weight || 1 }})</span>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
    <div v-else class="no-data">
      暂无历史数据
    </div>
  </div>
</template>

<script>
import { computed } from 'vue'

export default {
  name: 'HotStuffTable',
  props: {
    simulationResult: { type: Object, default: null },
    nodeCount: { type: Number, default: 6 }
  },
  setup (props) {
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

    // 获取复杂度对比数据
    const complexityComparison = computed(() => {
      // 优先从 simulationResult.stats.complexity_comparison 获取
      if (props.simulationResult?.stats?.complexity_comparison) {
        return props.simulationResult.stats.complexity_comparison
      }
      // 兼容：从 simulationResult 根级别获取（如果后端直接返回）
      if (props.simulationResult?.complexity_comparison) {
        return props.simulationResult.complexity_comparison
      }
      return null
    })

    // 按顺序排列的算法列表（用于展示）
    const comparisonAlgorithms = computed(() => {
      if (!complexityComparison.value) return []
      
      const comp = complexityComparison.value
      return [
        comp.double_hotstuff,  // 当前系统，放在第一位
        comp.hotstuff_pure,    // 传统 HotStuff
        comp.pbft_multi_layer, // 双层 PBFT
        comp.pbft_pure         // 传统 PBFT（最差，放在最后）
      ]
    })

    // 计算最大消息数（用于进度条比例）
    const maxMessages = computed(() => {
      if (!comparisonAlgorithms.value || comparisonAlgorithms.value.length === 0) return 1
      return Math.max(...comparisonAlgorithms.value.map(a => a.messages || 0), 1)
    })

    // 格式化数字（添加千位分隔符）
    const formatNumber = (num) => {
      if (num === null || num === undefined) return '0'
      return num.toLocaleString('en-US')
    }

    // 计算进度条宽度（百分比）
    const getProgressWidth = (messages) => {
      if (!maxMessages.value || maxMessages.value === 0) return 0
      return Math.min((messages / maxMessages.value) * 100, 100)
    }

    // 获取进度条样式类
    const getProgressBarClass = (key) => {
      if (key === 'double_hotstuff') return 'progress-current'
      if (key === 'hotstuff_pure') return 'progress-hotstuff'
      if (key === 'pbft_multi_layer') return 'progress-pbft-multi'
      if (key === 'pbft_pure') return 'progress-pbft-pure'
      return 'progress-default'
    }

    const getNodePhaseMessages = (nodeIndex, phase) => {
      const msgs = props.simulationResult?.messages || []
      if (!msgs || msgs.length === 0) return []

      // 只展示该节点作为发送方的消息，按 phase 分类
      return msgs.filter(msg => {
        if (!msg) return false
        const msgPhase = msg.phase
        const isPhaseMatch = msgPhase === phase
        const isFromNode = msg.src === nodeIndex
        // 处理特殊目标（all, group_leaders, group_members）
        const hasValidDst = msg.dst !== null && msg.dst !== undefined && 
                           (typeof msg.dst === 'number' || 
                            msg.dst === 'all' || 
                            msg.dst === 'group_leaders' || 
                            msg.dst === 'group_members')
        return isPhaseMatch && isFromNode && hasValidDst
      })
    }

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
      // 检查是否为 GroupVote（聚合投票）
      return msg?.is_group_vote === true || 
             (msg?.type === 'vote' && msg?.weight > 1) ||
             (msg?.type === 'qc' && msg?.qc?.is_multi_layer === true)
    }

    const getMsgClass = (msg) => {
      if (msg?.type === 'qc') {
        return 'qc-msg'
      }
      if (msg?.type === 'vote') {
        return 'vote-msg'
      }
      if (msg?.type === 'pre_prepare' || msg?.type === 'proposal') {
        return 'proposal-msg'
      }
      return 'other-msg'
    }

    return {
      nodes,
      complexityComparison,
      comparisonAlgorithms,
      maxMessages,
      formatNumber,
      getProgressWidth,
      getProgressBarClass,
      getNodePhaseMessages,
      msgKey,
      formatLabel,
      formatDst,
      isGroupVote,
      getMsgClass
    }
  }
}
</script>

<style scoped>
.hotstuff-table-container {
  width: 100%;
  max-width: 1000px;
  margin: 0 auto;
}

/* 复杂度对比面板样式 */
.complexity-panel {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 12px;
  padding: 25px;
  margin-bottom: 30px;
  color: white;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.2);
}

.complexity-panel h3 {
  margin: 0 0 20px 0;
  font-size: 1.4rem;
  text-align: center;
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
}

.comparison-table {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 20px;
  margin-bottom: 20px;
}

.algorithm-card {
  background: rgba(255, 255, 255, 0.15);
  backdrop-filter: blur(10px);
  border-radius: 12px;
  padding: 18px;
  border: 2px solid rgba(255, 255, 255, 0.2);
  transition: all 0.3s ease;
}

.algorithm-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.algorithm-card.current-system {
  background: linear-gradient(135deg, rgba(76, 175, 80, 0.3), rgba(56, 142, 60, 0.3));
  border: 3px solid #4CAF50;
  box-shadow: 0 0 20px rgba(76, 175, 80, 0.5);
}

.algorithm-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 15px;
  flex-wrap: wrap;
  gap: 8px;
}

.algorithm-name {
  font-size: 1.1rem;
  font-weight: bold;
  flex: 1;
  min-width: 0;
}

.current-badge {
  background: linear-gradient(135deg, #4CAF50, #45a049);
  color: white;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 0.75rem;
  font-weight: bold;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

.optimization-badge {
  background: linear-gradient(135deg, #FFD700, #FFA500);
  color: #333;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 0.75rem;
  font-weight: bold;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

.algorithm-stats {
  margin-bottom: 15px;
}

.stat-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-size: 0.9rem;
}

.stat-label {
  opacity: 0.9;
}

.stat-value {
  font-weight: bold;
  font-size: 1rem;
}

.stat-value.complexity {
  font-family: 'Courier New', monospace;
  background: rgba(0, 0, 0, 0.2);
  padding: 2px 8px;
  border-radius: 4px;
}

/* 进度条样式 */
.progress-container {
  margin-top: 12px;
}

.progress-bar-wrapper {
  width: 100%;
  height: 32px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 16px;
  overflow: hidden;
  position: relative;
  border: 1px solid rgba(255, 255, 255, 0.3);
}

.progress-bar {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding-right: 8px;
  transition: width 0.8s ease;
  border-radius: 16px;
  position: relative;
  min-width: 60px;
}

.progress-current {
  background: linear-gradient(90deg, #4CAF50, #66BB6A);
  box-shadow: 0 0 10px rgba(76, 175, 80, 0.6);
}

.progress-hotstuff {
  background: linear-gradient(90deg, #2196F3, #42A5F5);
}

.progress-pbft-multi {
  background: linear-gradient(90deg, #FF9800, #FFB74D);
}

.progress-pbft-pure {
  background: linear-gradient(90deg, #F44336, #EF5350);
}

.progress-text {
  color: white;
  font-size: 0.75rem;
  font-weight: bold;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
  white-space: nowrap;
}

.comparison-note {
  font-size: 0.95rem;
  opacity: 0.95;
  text-align: center;
  padding-top: 15px;
  border-top: 1px solid rgba(255, 255, 255, 0.3);
  line-height: 1.6;
}

.hotstuff-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 10px;
  font-size: 14px;
}

.hotstuff-table th,
.hotstuff-table td {
  border: 1px solid #ccc;
  padding: 6px 8px;
  text-align: left;
  vertical-align: top;
}

.hotstuff-table th {
  background: #f5f7fa;
}

.col-tip {
  display: block;
  font-size: 11px;
  color: #909399;
  font-weight: normal;
}

.msg-line {
  white-space: nowrap;
  margin-bottom: 4px;
  padding: 2px 4px;
  border-radius: 4px;
}

.msg-line.group-vote {
  background: linear-gradient(90deg, rgba(255, 215, 0, 0.2), rgba(255, 215, 0, 0.1));
  border-left: 3px solid #FFD700;
  font-weight: bold;
}

.msg-label {
  margin-left: 4px;
}

.group-vote-badge {
  display: inline-block;
  margin-left: 8px;
  padding: 2px 6px;
  background: linear-gradient(135deg, #FFD700, #FFA500);
  color: #333;
  border-radius: 12px;
  font-size: 0.75rem;
  font-weight: bold;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

.proposal-msg {
  color: #409eff;
  font-weight: 600;
}

.qc-msg {
  color: #67c23a;
  font-weight: 600;
}

.vote-msg {
  color: #e6a23c;
  font-weight: 600;
}

.other-msg {
  color: #606266;
}

.no-data {
  margin-top: 10px;
  text-align: center;
  color: #909399;
}
</style>


