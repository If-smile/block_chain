<template>
  <div class="terminal-page">
    <!-- Terminal Header -->
    <div class="terminal-header">
      <div class="header-left">
        <el-tag 
          :type="isLeader ? 'warning' : 'primary'" 
          effect="dark" 
          size="large"
          class="role-badge"
        >
          <el-icon><User /></el-icon>
          {{ isLeader ? 'LEADER' : 'REPLICA' }} - Node {{ nodeId }}
        </el-tag>
        
        <el-tag 
          :type="connectionStatus === 'connected' ? 'success' : 'danger'"
          effect="dark"
          size="large"
        >
          <el-icon>
            <Connection v-if="connectionStatus === 'connected'" />
            <Close v-else />
          </el-icon>
          {{ connectionStatus === 'connected' ? 'ONLINE' : 'OFFLINE' }}
        </el-tag>
        
        <el-tag type="info" effect="dark" size="large">
          <el-icon><View /></el-icon>
          VIEW {{ currentView }}
        </el-tag>
      </div>
      
      <div class="header-right">
        <el-button 
          size="small" 
          type="danger" 
          @click="leaveSession"
          :icon="SwitchButton"
        >
          Exit
        </el-button>
      </div>
    </div>
    
    <!-- Main Content Area -->
    <el-row :gutter="0" class="terminal-main">
      <!-- Left: Control Panel (40%) -->
      <el-col :span="10">
        <div class="control-panel">
          <div class="panel-header">
            <div class="header-line"></div>
            <span class="panel-title">CONTROL PANEL</span>
          </div>
          
          <div class="panel-content">
            <!-- Leader: Proposal Box -->
            <div v-if="isLeader" class="proposal-section">
              <div class="section-title">
                <el-icon><Edit /></el-icon>
                <span>Send Proposal</span>
              </div>
              
              <div class="proposal-input-group">
                <el-input
                  v-model="proposalInput"
                  placeholder="Enter proposal value..."
                  class="proposal-input"
                  size="large"
                >
                  <template #suffix>
                    <el-button
                      :icon="Promotion"
                      circle
                      type="primary"
                      @click="sendProposal"
                      :disabled="!proposalInput"
                    />
                  </template>
                </el-input>
              </div>
              
              <div class="proposal-quick-actions">
                <el-button 
                  @click="proposalInput = sessionConfig.proposalValue?.toString() || '0'"
                  size="small"
                  plain
                >
                  Use Default ({{ sessionConfig.proposalValue }})
                </el-button>
              </div>
            </div>
            
            <!-- Replica: Progress Ring -->
            <div v-else class="progress-section">
              <div class="section-title">
                <el-icon><Timer /></el-icon>
                <span>Consensus Progress</span>
              </div>
              
              <div class="progress-ring-container">
                <el-progress
                  type="circle"
                  :percentage="getPhasePercentage()"
                  :width="180"
                  :stroke-width="12"
                  :color="progressColors"
                >
                  <template #default="{ percentage }">
                    <div class="progress-content">
                      <div class="progress-value">{{ percentage }}%</div>
                      <div class="progress-phase">{{ getPhaseShortName(currentPhase) }}</div>
                    </div>
                  </template>
                </el-progress>
              </div>
              
              <div class="phase-timeline">
                <el-steps :active="phaseStep" finish-status="success" align-center>
                  <el-step title="Prepare" icon="DocumentChecked" />
                  <el-step title="Pre-Commit" icon="Document" />
                  <el-step title="Commit" icon="DocumentCopy" />
                  <el-step title="Decide" icon="Select" />
                </el-steps>
              </div>
            </div>
            
            <!-- Action Selection -->
            <div class="action-section">
              <el-divider content-position="left">
                <span class="divider-text">Node Actions</span>
              </el-divider>
              
              <div v-if="waitingForNextRound" class="waiting-box">
                <el-icon class="waiting-icon" :size="40"><Loading /></el-icon>
                <p>Waiting for next consensus round...</p>
              </div>
              
              <div v-else class="action-buttons">
                <el-button
                  :type="hasChosenAction && isNormalMode ? 'success' : 'default'"
                  @click="chooseNormalConsensus"
                  :disabled="hasChosenAction"
                  :icon="CircleCheck"
                  size="large"
                  class="action-btn"
                >
                  {{ hasChosenAction && isNormalMode ? '✓ Normal Mode' : 'Normal Consensus' }}
                </el-button>
                
                <el-button
                  :type="hasChosenAction && !isNormalMode ? 'danger' : 'default'"
                  @click="chooseByzantineAttack"
                  :disabled="hasChosenAction"
                  :icon="WarnTriangleFilled"
                  size="large"
                  class="action-btn"
                >
                  {{ hasChosenAction && !isNormalMode ? '✓ Byzantine Mode' : 'Byzantine Attack' }}
                </el-button>
              </div>
              
              <!-- Byzantine Attack Controls -->
              <div v-if="hasChosenAction && !isNormalMode" class="byzantine-controls">
                <el-alert
                  title="Byzantine Mode Active"
                  type="warning"
                  :closable="false"
                  show-icon
                  class="mode-alert"
                />
                
                <el-button
                  type="danger"
                  @click="sendErrorMessage"
                  :icon="Warning"
                  size="large"
                  class="error-btn"
                >
                  Send Error Message
                </el-button>
              </div>
              
              <div v-else-if="hasChosenAction && isNormalMode" class="normal-mode-info">
                <el-alert
                  title="Normal Mode Active"
                  description="Robot is handling consensus protocol for you."
                  type="success"
                  :closable="false"
                  show-icon
                />
              </div>
            </div>
            
            <!-- Consensus Status -->
            <div class="status-section">
              <el-divider content-position="left">
                <span class="divider-text">Network Status</span>
              </el-divider>
              
              <el-descriptions :column="1" size="small" border class="status-table">
                <el-descriptions-item label="Current Leader">
                  Node {{ currentLeaderId }}
                </el-descriptions-item>
                <el-descriptions-item label="Current Phase">
                  {{ getPhaseDisplayName(currentPhase) }}
                </el-descriptions-item>
                <el-descriptions-item label="Accepted Value">
                  {{ getAcceptedContentDisplay() }}
                </el-descriptions-item>
                <el-descriptions-item label="Network Reliability">
                  {{ sessionConfig.messageDeliveryRate ?? '—' }}%
                </el-descriptions-item>
              </el-descriptions>
            </div>
          </div>
        </div>
      </el-col>
      
      <!-- Right: Audit Log (60%) -->
      <el-col :span="14">
        <div class="audit-log">
          <div class="log-header">
            <div class="header-line"></div>
            <span class="log-title">AUDIT LOG</span>
            <div class="log-actions">
              <el-button 
                size="small" 
                :icon="Delete"
                @click="clearLogs"
                text
              >
                Clear
              </el-button>
            </div>
          </div>
          
          <div class="log-content" ref="logContainer" v-auto-animate>
            <div 
              v-for="log in auditLogs" 
              :key="log.id"
              class="log-entry"
              :class="`log-${log.type}`"
            >
              <span class="log-time">[{{ log.time }}]</span>
              <span class="log-type">[{{ log.typeLabel }}]</span>
              <span class="log-message">{{ log.message }}</span>
            </div>
            
            <div v-if="auditLogs.length === 0" class="log-empty">
              <el-icon :size="40"><Document /></el-icon>
              <p>No logs yet. Waiting for network activity...</p>
            </div>
          </div>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  User,
  Connection,
  Close,
  View,
  SwitchButton,
  Edit,
  Promotion,
  Timer,
  Loading,
  CircleCheck,
  WarnTriangleFilled,
  Warning,
  Delete,
  Document
} from '@element-plus/icons-vue'
import io from 'socket.io-client'

const route = useRoute()
const router = useRouter()

// Route parameters
const sessionId = route.params.sessionId
const nodeId = parseInt(route.params.nodeId)

// Reactive state
const socket = ref(null)
const connectionStatus = ref('connecting')
const sessionConfig = ref({
  nodeCount: 5,
  topology: 'full',
  proposalValue: 0,
  proposalContent: '',
  faultyNodes: 1,
  messageDeliveryRate: 100
})
const connectedNodes = ref([])
const currentPhase = ref('prepare')
const phaseStep = ref(0)
const currentView = ref(0)
const currentLeaderId = ref(0)
const acceptedValue = ref(null)
const receivedMessages = ref([])

// Action state
const hasChosenAction = ref(false)
const isNormalMode = ref(false)
const waitingForNextRound = ref(true)

// UI state
const proposalInput = ref('')
const logContainer = ref(null)
const auditLogs = ref([])

// Computed
const isLeader = computed(() => nodeId === currentLeaderId.value)

const progressColors = [
  { color: '#f56c6c', percentage: 25 },
  { color: '#e6a23c', percentage: 50 },
  { color: '#5cb87a', percentage: 75 },
  { color: '#1989fa', percentage: 100 }
]

// Methods
const addLog = (type, message) => {
  const log = {
    id: Date.now() + Math.random(),
    time: new Date().toLocaleTimeString(),
    type: type,
    typeLabel: type.toUpperCase(),
    message: message
  }
  auditLogs.value.unshift(log)
  
  // Limit logs to 100 entries
  if (auditLogs.value.length > 100) {
    auditLogs.value = auditLogs.value.slice(0, 100)
  }
  
  // Auto-scroll to bottom (top in this case since we prepend)
  nextTick(() => {
    if (logContainer.value) {
      logContainer.value.scrollTop = 0
    }
  })
}

const connectToServer = () => {
  socket.value = io(window.location.origin, {
    query: { sessionId, nodeId }
  })

  socket.value.on('connect', () => {
    connectionStatus.value = 'connected'
    addLog('info', `Node ${nodeId} connected to session ${sessionId}`)
    ElMessage.success('Connected to server')
  })

  socket.value.on('disconnect', () => {
    connectionStatus.value = 'disconnected'
    addLog('error', 'Disconnected from server')
    ElMessage.warning('Connection lost')
  })

  socket.value.on('session_config', (config) => {
    sessionConfig.value = { ...sessionConfig.value, ...config }
    acceptedValue.value = config.proposalValue
    addLog('info', `Session configuration received: ${config.nodeCount} nodes`)
  })

  socket.value.on('node_connected', (data) => {
    if (!connectedNodes.value.includes(data.nodeId)) {
      connectedNodes.value.push(data.nodeId)
    }
    addLog('info', `Node ${data.nodeId} joined the network`)
  })

  socket.value.on('node_disconnected', (data) => {
    const index = connectedNodes.value.indexOf(data.nodeId)
    if (index > -1) {
      connectedNodes.value.splice(index, 1)
    }
    addLog('warn', `Node ${data.nodeId} left the network`)
  })

  socket.value.on('phase_update', (data) => {
    currentPhase.value = data.phase
    phaseStep.value = data.step
    if (data.view !== undefined) currentView.value = data.view
    if (data.leader !== undefined) currentLeaderId.value = data.leader
    
    // 解锁等待状态：收到任何 phase_update 都表示共识已启动
    if (waitingForNextRound.value) {
      waitingForNextRound.value = false
      addLog('info', '✓ Consensus initialized, UI unlocked')
    }
    
    addLog('info', `Phase updated: ${data.phase.toUpperCase()} (Step ${data.step}/4)`)
  })

  socket.value.on('new_round', (data) => {
    currentView.value = data.view !== undefined ? data.view : currentView.value
    currentPhase.value = data.phase
    phaseStep.value = data.step
    receivedMessages.value = []
    hasChosenAction.value = false
    isNormalMode.value = false
    waitingForNextRound.value = false
    addLog('info', `🔄 New consensus round started (View ${data.view || currentView.value})`)
    ElMessage.info(`Round ${data.round || currentView.value} started`)
  })

  socket.value.on('message_received', (message) => {
    receivedMessages.value.unshift({
      ...message,
      id: Date.now() + Math.random(),
      timestamp: new Date()
    })
    
    if (message.type === 'pre_prepare' && message.from === 0) {
      acceptedValue.value = message.value
    }
    
    addLog('info', `📩 Message from Node ${message.from}: ${getMessageTypeName(message.type)} (value: ${message.value})`)
  })

  socket.value.on('consensus_result', (result) => {
    const logType = result.status === '共识成功' ? 'info' : 'error'
    addLog(logType, `🎯 Consensus Result: ${result.status} - ${result.description}`)
    
    if (result.status === '共识成功') {
      ElMessage.success(`Consensus: ${result.description}`)
    } else {
      ElMessage.error(`Consensus Failed: ${result.description}`)
    }
  })

  socket.value.on('error', (error) => {
    addLog('error', `❌ Error: ${error.message}`)
    ElMessage.error(`Error: ${error.message}`)
  })
}

const leaveSession = async () => {
  try {
    await ElMessageBox.confirm('Leave this session?', 'Confirm', {
      confirmButtonText: 'Leave',
      cancelButtonText: 'Cancel',
      type: 'warning'
    })
    
    if (socket.value) {
      socket.value.disconnect()
    }
    router.push('/')
  } catch {
    // User cancelled
  }
}

const chooseNormalConsensus = () => {
  hasChosenAction.value = true
  isNormalMode.value = true
  
  if (socket.value) {
    socket.value.emit('choose_normal_consensus', { sessionId, nodeId })
  }
  
  addLog('info', '✓ Normal consensus mode activated (robot proxy)')
  ElMessage.success('Normal mode: Robot will handle consensus')
}

const chooseByzantineAttack = () => {
  hasChosenAction.value = true
  isNormalMode.value = false
  
  if (socket.value) {
    socket.value.emit('choose_byzantine_attack', { sessionId, nodeId })
  }
  
  addLog('warn', '⚠️ Byzantine attack mode activated')
  ElMessage.warning('Byzantine mode: You can send error messages')
}

const sendErrorMessage = () => {
  if (!hasChosenAction.value || isNormalMode.value) {
    ElMessage.error('Switch to Byzantine mode first')
    return
  }
  
  if (socket.value) {
    const errorValue = acceptedValue.value === 0 ? 1 : 0
    const errorMessage = {
      sessionId,
      nodeId,
      value: errorValue,
      byzantine: true
    }
    
    if (currentPhase.value === 'prepare') {
      socket.value.emit('send_prepare', errorMessage)
    } else if (currentPhase.value === 'commit') {
      socket.value.emit('send_commit', errorMessage)
    }
    
    addLog('error', `🦹 Sent malicious message with value ${errorValue}`)
    ElMessage.warning(`Malicious message sent: ${errorValue}`)
  }
}

const sendProposal = () => {
  if (!proposalInput.value) return
  
  // Implement proposal sending logic
  addLog('info', `📤 Proposal sent: ${proposalInput.value}`)
  ElMessage.success('Proposal sent')
  proposalInput.value = ''
}

const clearLogs = () => {
  auditLogs.value = []
  ElMessage.success('Logs cleared')
}

const getPhasePercentage = () => {
  return Math.round((phaseStep.value / 4) * 100)
}

const getPhaseShortName = (phase) => {
  const names = {
    'prepare': 'PREP',
    'pre-commit': 'PRE-C',
    'commit': 'COMMIT',
    'decide': 'DECIDE'
  }
  return names[phase] || phase.toUpperCase()
}

const getPhaseDisplayName = (phase) => {
  const names = {
    'new-view': 'New-View',
    'pre-prepare': 'Prepare',
    'prepare': 'Prepare',
    'pre-commit': 'Pre-Commit',
    'commit': 'Commit',
    'decide': 'Decide',
    'reply': 'Decide'
  }
  return names[phase] || phase
}

const getMessageTypeName = (type) => {
  const names = {
    'pre-prepare': 'PROPOSAL',
    'prepare': 'PREPARE',
    'commit': 'COMMIT',
    'reply': 'REPLY'
  }
  return names[type] || type.toUpperCase()
}

const getAcceptedContentDisplay = () => {
  const proposalContent = sessionConfig.value.proposalContent
  if (proposalContent && proposalContent.trim()) {
    return proposalContent
  }
  if (acceptedValue.value === null) {
    return '—'
  }
  return acceptedValue.value === 0 ? 'Option A' : 'Option B'
}

// Lifecycle
onMounted(() => {
  connectToServer()
  addLog('info', `🚀 Terminal initialized for Node ${nodeId}`)
})

onUnmounted(() => {
  if (socket.value) {
    socket.value.disconnect()
  }
})
</script>

<style scoped>
/* ========== Terminal Page ========== */
.terminal-page {
  min-height: calc(100vh - 64px);
  background: #f0f2f5;
  padding: 0;
}

/* ========== Header ========== */
.terminal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  background: linear-gradient(135deg, #2c3e50 0%, #34495e 100%);
  border-bottom: 3px solid #1890ff;
}

.header-left {
  display: flex;
  gap: 12px;
  align-items: center;
}

.role-badge {
  font-weight: 700;
  letter-spacing: 1px;
}

.header-right {
  display: flex;
  gap: 8px;
}

/* ========== Main Content ========== */
.terminal-main {
  height: calc(100vh - 120px);
}

/* ========== Control Panel ========== */
.control-panel {
  height: 100%;
  background: #fff;
  border-right: 2px solid #e8e8e8;
  display: flex;
  flex-direction: column;
}

.panel-header,
.log-header {
  padding: 16px 20px;
  background: #fafafa;
  border-bottom: 1px solid #e8e8e8;
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-line {
  width: 3px;
  height: 18px;
  background: #1890ff;
  border-radius: 2px;
}

.panel-title,
.log-title {
  font-size: 14px;
  font-weight: 700;
  color: #303133;
  letter-spacing: 1px;
}

.log-actions {
  margin-left: auto;
}

.panel-content {
  flex: 1;
  padding: 20px;
  overflow-y: auto;
}

/* ========== Sections ========== */
.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: #606266;
  margin-bottom: 16px;
}

.divider-text {
  font-size: 13px;
  font-weight: 600;
  color: #909399;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* ========== Proposal Section ========== */
.proposal-section {
  margin-bottom: 24px;
}

.proposal-input-group {
  margin-bottom: 12px;
}

.proposal-input :deep(.el-input__wrapper) {
  border-radius: 8px;
  box-shadow: 0 0 0 1px #d9d9d9 inset;
  transition: all 0.3s;
}

.proposal-input :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #1890ff inset;
}

.proposal-input :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 2px #1890ff inset;
}

.proposal-quick-actions {
  display: flex;
  gap: 8px;
}

/* ========== Progress Section ========== */
.progress-section {
  margin-bottom: 24px;
}

.progress-ring-container {
  display: flex;
  justify-content: center;
  margin: 24px 0;
}

.progress-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.progress-value {
  font-size: 28px;
  font-weight: 700;
  color: #303133;
}

.progress-phase {
  font-size: 12px;
  color: #909399;
  font-weight: 600;
  letter-spacing: 1px;
}

.phase-timeline {
  margin-top: 24px;
}

/* ========== Action Section ========== */
.action-section {
  margin-bottom: 24px;
}

.waiting-box {
  text-align: center;
  padding: 40px 20px;
  color: #909399;
}

.waiting-icon {
  margin-bottom: 16px;
  color: #1890ff;
  animation: rotate 2s linear infinite;
}

@keyframes rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.action-buttons {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.action-btn {
  width: 100%;
  height: 44px;
  font-weight: 600;
  letter-spacing: 0.5px;
}

.byzantine-controls {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.mode-alert {
  border-radius: 6px;
}

.error-btn {
  width: 100%;
  height: 44px;
  font-weight: 600;
}

.normal-mode-info {
  margin-top: 16px;
}

/* ========== Status Section ========== */
.status-section {
  margin-top: 24px;
}

.status-table {
  font-size: 13px;
}

.status-table :deep(.el-descriptions__label) {
  font-weight: 600;
  color: #606266;
}

/* ========== Audit Log ========== */
.audit-log {
  height: 100%;
  background: #1e1e1e;
  display: flex;
  flex-direction: column;
}

.audit-log .log-header {
  background: #2d2d2d;
  border-bottom: 1px solid #3e3e3e;
}

.audit-log .panel-title,
.audit-log .log-title {
  color: #d4d4d4;
}

.log-content {
  flex: 1;
  padding: 12px;
  overflow-y: auto;
  font-family: 'JetBrains Mono', 'Roboto Mono', 'Fira Code', 'Courier New', Consolas, monospace !important;
  font-size: 13px;
  line-height: 1.6;
}

.log-entry {
  padding: 6px 8px;
  margin-bottom: 4px;
  border-radius: 4px;
  transition: background 0.2s;
}

.log-entry:hover {
  background: rgba(255, 255, 255, 0.05);
}

.log-time {
  color: #858585;
  margin-right: 8px;
}

.log-type {
  margin-right: 8px;
  font-weight: 600;
}

.log-message {
  color: #d4d4d4;
}

/* Log Type Colors */
.log-info .log-type {
  color: #4ec9b0;
}

.log-warn .log-type {
  color: #dcdcaa;
}

.log-error .log-type {
  color: #f48771;
}

.log-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #858585;
  gap: 16px;
}

/* ========== Scrollbar ========== */
.panel-content::-webkit-scrollbar,
.log-content::-webkit-scrollbar {
  width: 6px;
}

.panel-content::-webkit-scrollbar-track {
  background: #f1f1f1;
}

.log-content::-webkit-scrollbar-track {
  background: #2d2d2d;
}

.panel-content::-webkit-scrollbar-thumb {
  background: #d0d0d0;
  border-radius: 3px;
}

.log-content::-webkit-scrollbar-thumb {
  background: #4a4a4a;
  border-radius: 3px;
}

.panel-content::-webkit-scrollbar-thumb:hover {
  background: #b0b0b0;
}

.log-content::-webkit-scrollbar-thumb:hover {
  background: #5a5a5a;
}

/* ========== Responsive ========== */
@media (max-width: 1200px) {
  .terminal-main {
    height: auto;
  }
  
  .control-panel,
  .audit-log {
    height: auto;
    min-height: 400px;
  }
}
</style>
