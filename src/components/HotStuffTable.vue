<template>
  <div class="hotstuff-table-container">
    <h2>HotStuff Stages</h2>
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
              :class="getMsgClass(msg)"
            >
              {{ msg.src }}→{{ msg.dst }}:
              <span class="msg-label">{{ formatLabel(msg) }}</span>
            </div>
          </td>
          <!-- Pre-Commit column -->
          <td>
            <div
              v-for="msg in getNodePhaseMessages(node, 'pre-commit')"
              :key="msgKey(msg)"
              class="msg-line"
              :class="getMsgClass(msg)"
            >
              {{ msg.src }}→{{ msg.dst }}:
              <span class="msg-label">{{ formatLabel(msg) }}</span>
            </div>
          </td>
          <!-- Commit column -->
          <td>
            <div
              v-for="msg in getNodePhaseMessages(node, 'commit')"
              :key="msgKey(msg)"
              class="msg-line"
              :class="getMsgClass(msg)"
            >
              {{ msg.src }}→{{ msg.dst }}:
              <span class="msg-label">{{ formatLabel(msg) }}</span>
            </div>
          </td>
          <!-- Decide column -->
          <td>
            <div
              v-for="msg in getNodePhaseMessages(node, 'decide')"
              :key="msgKey(msg)"
              class="msg-line"
              :class="getMsgClass(msg)"
            >
              {{ msg.src }}→{{ msg.dst }}:
              <span class="msg-label">{{ formatLabel(msg) }}</span>
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

    const getNodePhaseMessages = (nodeIndex, phase) => {
      const msgs = props.simulationResult?.messages || []
      if (!msgs || msgs.length === 0) return []

      // 只展示该节点作为发送方的消息，按 phase 分类
      return msgs.filter(msg => {
        if (!msg) return false
        const msgPhase = msg.phase
        const isPhaseMatch = msgPhase === phase
        const isFromNode = msg.src === nodeIndex
        return isPhaseMatch && isFromNode && msg.dst !== null && msg.dst !== undefined
      })
    }

    const msgKey = (msg) => {
      if (!msg) return 'invalid-key'
      return `${msg.src}-${msg.dst ?? 'null'}-${msg.type ?? 'msg'}-${msg.value}`
    }

    const formatLabel = (msg) => {
      const value = msg?.value
      if (msg?.type === 'qc') {
        return `QC(${value})`
      }
      if (msg?.type === 'vote') {
        return `VOTE(${value})`
      }
      if (msg?.type === 'pre_prepare' || msg?.type === 'proposal') {
        return `PROPOSAL(${value})`
      }
      return `${msg?.type ?? 'MSG'}(${value})`
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
      getNodePhaseMessages,
      msgKey,
      formatLabel,
      getMsgClass
    }
  }
}
</script>

<style scoped>
.hotstuff-table-container {
  width: 100%;
  max-width: 800px;
  margin: 0 auto;
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
  margin-bottom: 2px;
}

.msg-label {
  margin-left: 4px;
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


