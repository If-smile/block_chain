<template>
  <div class="node-page">
    <el-container>
      <el-header class="header">
        <div class="header-content">
          <div class="node-info">
            <h2>参与者 {{ nodeId }}</h2>
            <el-tag :type="connectionStatus === 'connected' ? 'success' : 'danger'">
              {{ connectionStatus === 'connected' ? '已连接' : '未连接' }}
            </el-tag>
            <el-tag type="danger" effect="dark">🦹 拜占庭节点（人类玩家）</el-tag>
          </div>
          <div class="session-info">
            <span>会话: {{ sessionId }}</span>
            <el-tag type="primary">当前视图: {{ currentView }}</el-tag>
            <el-button size="small" @click="leaveSession" type="danger">离开会话</el-button>
          </div>
        </div>
      </el-header>
      
      <el-main class="main-content">
        <el-row :gutter="20">
          <!-- Left: Consensus Progress -->
          <el-col :span="6">
            <!-- Advanced Options Toggle -->
            <div style="margin-bottom: 15px;">
              <el-button 
                @click="showAdvancedOptions = !showAdvancedOptions" 
                :type="showAdvancedOptions ? 'primary' : 'info'"
                size="default"
                style="width: 100%;"
              >
                {{ showAdvancedOptions ? '隐藏高级选项' : '显示高级选项' }}
              </el-button>
            </div>
            
            <el-card class="progress-card">
              <template #header>
                <div class="card-header">
                  <span>共识进度</span>
                  <el-tag type="primary" size="large" effect="dark">当前视图: {{ currentView }}</el-tag>
                </div>
              </template>
              
              <div class="consensus-progress">
                <!-- Consensus Progress Bar -->
                <div class="phase-progress">
                  <el-progress 
                    :percentage="getPhasePercentage()" 
                    :status="getPhaseStatus()"
                    :stroke-width="8"
                  />
                  <div class="phase-steps">
                    <el-steps :active="phaseStep" finish-status="success" simple>
                      <el-step title="Prepare" description="准备阶段" />
                      <el-step title="Pre-Commit" description="预提交阶段" />
                      <el-step title="Commit" description="提交阶段" />
                      <el-step title="Decide" description="决定阶段" />
                    </el-steps>
                  </div>
                </div>
                
                <!-- Current Status -->
                <div class="current-status">
                  <h4>当前状态</h4>
                  <el-descriptions :column="1" border size="small">
                    <el-descriptions-item label="当前视图">{{ currentView }}</el-descriptions-item>
                    <el-descriptions-item label="当前 Leader">节点 {{ currentLeaderId }}</el-descriptions-item>
                    <el-descriptions-item label="当前阶段">{{ getPhaseDisplayName(currentPhase) }}</el-descriptions-item>
                    <el-descriptions-item label="已接受内容">{{ getAcceptedContentDisplay() }}</el-descriptions-item>
                    <el-descriptions-item label="网络可靠性">{{ sessionConfig.messageDeliveryRate ?? '未设置' }}%</el-descriptions-item>
                  </el-descriptions>
                </div>
                
                <!-- Human Node Actions -->
                <div class="human-node-actions">
                  <h4>操作选择</h4>
                  
                  <!-- 等待下一轮共识 -->
                  <div v-if="waitingForNextRound">
                    <el-alert
                      title="等待下一轮共识开始"
                      description="您在当前轮次进入系统，将在下一轮共识开始时参与。请耐心等待..."
                      type="info"
                      :closable="false"
                      show-icon
                    />
                  </div>
                  
                  <!-- 可以选择操作 -->
                  <div v-else>
                    <div class="action-buttons" style="display: flex; flex-direction: column; align-items: stretch;">
                      <el-button 
                        type="success" 
                        @click="chooseNormalConsensus" 
                        :disabled="hasChosenAction"
                        size="default"
                        style="width: 100%; margin-bottom: 15px; padding: 8px 20px; border-width: 1px; box-sizing: border-box;"
                      >
                        {{ hasChosenAction && isNormalMode ? '✓ 已选择正常共识（机器人代理）' : '正常共识' }}
                      </el-button>
                      <el-button 
                        type="danger" 
                        @click="chooseByzantineAttack" 
                        :disabled="hasChosenAction"
                        size="default"
                        style="width: 100%; padding: 8px 20px; border-width: 1px; box-sizing: border-box;"
                      >
                        {{ hasChosenAction && !isNormalMode ? '✓ 已选择拜占庭攻击' : '拜占庭攻击' }}
                      </el-button>
                    </div>
                    <div class="action-tip" style="margin-top: 10px;">
                      <el-alert
                        v-if="!hasChosenAction"
                        title="请选择本轮的操作方式"
                        description="选择正常共识后，机器人将代替您执行正确的PBFT流程；选择拜占庭攻击后，您可以手动发送错误信息。"
                        type="info"
                        :closable="false"
                      />
                      <el-alert
                        v-if="hasChosenAction && isNormalMode"
                        title="机器人代理模式"
                        description="机器人正在代替您执行正确的PBFT流程，您无需操作。"
                        type="success"
                        :closable="false"
                      />
                      <el-alert
                        v-if="hasChosenAction && !isNormalMode"
                        title="拜占庭攻击模式"
                        description="您可以在适当时机发送错误信息来干扰共识。"
                        type="warning"
                        :closable="false"
                      />
                    </div>
                  </div>
                </div>



                <!-- Byzantine Attack Control Area (only show when Byzantine mode chosen) -->
                <div class="attack-control" v-if="hasChosenAction && !isNormalMode">
                  <el-divider content-position="left">
                    <span style="color: #f56c6c; font-weight: bold;">🦹 拜占庭攻击操作</span>
                  </el-divider>
                  
                  <div class="simple-attack-control">
                    <el-button 
                      type="danger" 
                      @click="sendErrorMessage" 
                      style="width: 100%"
                      size="large"
                    >
                      发送错误信息
                    </el-button>
                    <div class="attack-tip" style="margin-top: 10px;">
                      <el-tag type="info" size="small">点击按钮发送与当前共识值相反的错误信息</el-tag>
                    </div>
                  </div>
                </div>
                
                <!-- Consensus Result Display -->
                <div class="consensus-result-control" style="margin-top: 20px; border-top: 1px solid #e4e7ed; padding-top: 15px;">
                  <el-button 
                    type="primary" 
                    @click="showConsensusResult" 
                    size="large"
                    style="width: 100%"
                  >
                    显示共识结果
                  </el-button>
                </div>
              </div>
            </el-card>
          </el-col>
          
          <!-- Middle: Received Messages -->
          <el-col :span="6" v-if="showAdvancedOptions">
            <el-card class="messages-card">
              <template #header>
                <div class="card-header">
                  <span>收到的消息</span>
                  <div>
                    <el-button size="small" @click="exportMessages">导出</el-button>
                    <el-button size="small" @click="clearMessages">清除</el-button>
                  </div>
                </div>
              </template>
              
              <div class="messages-container">
                <div class="messages-header">
                  <span>消息数量: {{ receivedMessages.length }}</span>
                </div>
                
                <div class="message-list">
                  <div 
                    v-for="msg in receivedMessages.slice(0, 8)" 
                    :key="msg.id"
                    class="message-item-compact"
                  >
                    <div class="message-header-compact">
                      <span class="message-from">来自: 参与者{{ msg.from }}</span>
                      <span class="message-time">{{ formatTime(msg.timestamp) }}</span>
                    </div>
                    <div class="message-content-compact">
                      <span class="message-type">{{ getMessageTypeName(msg.type) }}</span>
                      <span class="message-value" v-if="msg.value !== null">
                        内容: {{ msg.value === -1 ? '拒绝' : (msg.value === 0 ? '选项A' : '选项B') }}
                      </span>
                    </div>
                  </div>
                </div>
                
                <div v-if="receivedMessages.length === 0" class="no-messages">
                  <el-empty description="暂无消息" :image-size="60" />
                </div>
              </div>
            </el-card>
          </el-col>
          
          <!-- Right: Topology and Consensus Results -->
          <el-col :span="12" v-if="showAdvancedOptions">
            <!-- Topology -->
            <el-card class="topology-card">
              <template #header>
                <div class="card-header">
                  <span>网络拓扑图</span>
                  <el-button size="small" @click="refreshTopology">刷新</el-button>
                </div>
              </template>
              
              <div class="dynamic-topology">
                <div class="topology-info">
                  <p><strong>网络类型:</strong> {{ getTopologyName(sessionConfig.topology) }}</p>
                  <p><strong>总参与者:</strong> {{ sessionConfig.nodeCount }}</p>
                  <p><strong>活跃连接:</strong> {{ getActiveConnections() }}</p>
                </div>
                
                <!-- Topology Container -->
                <div class="topology-container">
                  <!-- Connection Lines -->
                  <svg class="connection-lines" :width="topologyWidth" :height="topologyHeight">
                    <line 
                      v-for="connection in topologyConnections" 
                      :key="`${connection.from}-${connection.to}`"
                      :x1="connection.x1" 
                      :y1="connection.y1" 
                      :x2="connection.x2" 
                      :y2="connection.y2"
                      :class="connection.active ? 'active-connection' : 'inactive-connection'"
                    />
                  </svg>
                  
                  <!-- Nodes -->
                  <div 
                    v-for="i in sessionConfig.nodeCount" 
                    :key="i-1"
                    class="topology-node"
                    :class="{
                      'current-node': (i-1) === nodeId,
                      'proposer': (i-1) === 0,
                      'visible-node': isNodeVisible(i-1),
                      'invisible-node': !isNodeVisible(i-1),
                      'has-messages': hasNodeMessages(i-1),
                      'active': isNodeActive(i-1)
                    }"
                    :style="{
                      left: getNodeX(i-1) + 'px',
                      top: getNodeY(i-1) + 'px'
                    }"
                    @click="showNodeDetails(i-1)"
                  >
                    <div class="node-number">{{ i-1 }}</div>
                    <div class="node-status-indicator" v-if="isNodeActive(i-1)"></div>
                    <div class="message-count" v-if="getNodeMessageCount(i-1) > 0">
                      {{ getNodeMessageCount(i-1) }}
                    </div>
                  </div>
                </div>
                
              </div>
            </el-card>
            
          </el-col>
        </el-row>
      </el-main>
    </el-container>
    
    <!-- Node Details Dialog -->
    <el-dialog v-model="nodeDetailsVisible" title="参与者详情" width="500px">
      <div v-if="selectedNode !== null">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="参与者ID">{{ selectedNode }}</el-descriptions-item>
          <el-descriptions-item label="连接状态">
            <el-tag :type="connectedNodes.includes(selectedNode) ? 'success' : 'danger'">
              {{ connectedNodes.includes(selectedNode) ? '已连接' : '未连接' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="角色">{{ selectedNode === 0 ? '提议者' : '验证者' }}</el-descriptions-item>
          <el-descriptions-item label="消息数量">{{ getNodeMessageCount(selectedNode) }}</el-descriptions-item>
        </el-descriptions>
        
        <div class="node-messages" style="margin-top: 20px;">
          <h4>来自此参与者的消息</h4>
          <div v-for="msg in getNodeMessages(selectedNode)" :key="msg.id" class="message-item">
            <div class="message-header">
              <span>{{ getMessageTypeName(msg.type) }}</span>
              <span>{{ formatTime(msg.timestamp) }}</span>
            </div>
            <div class="message-content">
              内容: {{ msg.value === -1 ? '拒绝' : (msg.value !== null ? (msg.value === 0 ? (sessionConfig.proposalContent || '选项A') : (sessionConfig.proposalContent || '选项B')) : '无') }}
            </div>
          </div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import io from 'socket.io-client'

const route = useRoute()
const router = useRouter()

// Route parameters
const sessionId = route.params.sessionId
const nodeId = parseInt(route.params.nodeId)

// Reactive data
const socket = ref(null)
const connectionStatus = ref('connecting')
const sessionConfig = ref({
  nodeCount: 5,
  topology: 'full',
  proposalValue: 0,
  proposalContent: '',
  faultyNodes: 1,
  maliciousProposer: false,
  allowTampering: false,
  messageDeliveryRate: 100
})
const connectedNodes = ref([])
const currentPhase = ref('pre-prepare')
const phaseStep = ref(0)
const currentRound = ref(1) // 兼容旧逻辑
const currentView = ref(0)
const currentLeaderId = ref(0)
const acceptedValue = ref(null)
const receivedMessages = ref([])

// Human node action choice
const hasChosenAction = ref(false)
const isNormalMode = ref(false)
const waitingForNextRound = ref(true)  // 初始时等待下一轮共识
const showAdvancedOptions = ref(false)  // 控制高级选项显示
const nodeDetailsVisible = ref(false)
const selectedNode = ref(null)

// Topology related
const topologyWidth = ref(500)
const topologyHeight = ref(400)
const topologyConnections = ref([])


// Message sending form (custom message functionality removed)
const messageForm = reactive({
  type: 'prepare',
  value: 0,
  target: 'all'
})


// Methods
const connectToServer = () => {
  socket.value = io(window.location.origin, {
    query: {
      sessionId,
      nodeId
    }
  })

  socket.value.on('connect', () => {
    connectionStatus.value = 'connected'
    ElMessage.success('连接成功')
  })

  socket.value.on('disconnect', () => {
    connectionStatus.value = 'disconnected'
    ElMessage.warning('连接断开')
  })

  socket.value.on('session_config', (config) => {
    console.log('Received session config:', config)
    console.log('Proposal content check:', {
      proposalContent: config.proposalContent,
      hasProposalContent: config.proposalContent && config.proposalContent.trim(),
      proposalValue: config.proposalValue
    })
    
    // Merge configuration, ensure all fields exist
    sessionConfig.value = {
      ...sessionConfig.value,
      ...config
    }
    console.log('Merged configuration:', sessionConfig.value)
    console.log('Final proposalContent:', sessionConfig.value.proposalContent)
    
    // Set accepted value to proposal value
    acceptedValue.value = config.proposalValue
    console.log('Set acceptedValue:', acceptedValue.value)
    
    refreshTopology()
  })

  socket.value.on('node_connected', (data) => {
    if (!connectedNodes.value.includes(data.nodeId)) {
      connectedNodes.value.push(data.nodeId)
    }
    refreshTopology()
  })

  socket.value.on('node_disconnected', (data) => {
    const index = connectedNodes.value.indexOf(data.nodeId)
    if (index > -1) {
      connectedNodes.value.splice(index, 1)
    }
    refreshTopology()
  })

  socket.value.on('phase_update', (data) => {
    currentPhase.value = data.phase
    phaseStep.value = data.step
    if (data.view !== undefined) {
      currentView.value = data.view
    }
    if (data.leader !== undefined) {
      currentLeaderId.value = data.leader
    }
    refreshTopology()
  })
  
  socket.value.on('new_round', (data) => {
    console.log('进入新一轮共识:', data)
    currentRound.value = data.round
    if (data.view !== undefined) {
      currentView.value = data.view
    }
    currentPhase.value = data.phase
    phaseStep.value = data.step
    receivedMessages.value = []  // 清空消息列表
    
    // 重置操作选择
    hasChosenAction.value = false
    isNormalMode.value = false
    waitingForNextRound.value = false  // 可以参与共识了
    
    ElMessage.info(`开始第${data.round}轮共识`)
  })

  socket.value.on('message_received', (message) => {
    receivedMessages.value.unshift({
      ...message,
      id: Date.now() + Math.random(),
      timestamp: new Date()
    })
    
    // If it's a pre-prepare message, set the accepted value
    if (message.type === 'pre_prepare' && message.from === 0) {
      acceptedValue.value = message.value
    }
    
    refreshTopology()
  })

  socket.value.on('consensus_result', (result) => {
    console.log('收到共识结果:', result)
    console.log('共识结果状态:', result.status)
    console.log('共识结果描述:', result.description)
    
    // 根据共识结果显示不同的消息
    if (result.status === '共识成功') {
      console.log('显示成功消息')
      ElMessage.success(`共识成功: ${result.description}`)
    } else if (result.status === '共识失败') {
      console.log('显示失败消息')
      ElMessage.error(`共识失败: ${result.description}`)
    } else if (result.status === '拒绝提议') {
      console.log('显示拒绝消息')
      ElMessage.warning(`拒绝提议: ${result.description}`)
    } else if (result.status === '无诚实节点') {
      console.log('显示无诚实节点消息')
      ElMessage.error(`无诚实节点: ${result.description}`)
    } else {
      console.log('显示其他消息')
      ElMessage.info(`共识结果: ${result.status} - ${result.description}`)
    }
  })

  socket.value.on('error', (error) => {
    ElMessage.error(`错误: ${error.message}`)
  })
}

const leaveSession = async () => {
  try {
    await ElMessageBox.confirm('确定要离开会话吗？', '确认', {
      confirmButtonText: '确认',
      cancelButtonText: '取消',
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
  
  // 通知后端，这个节点选择正常共识，由机器人代理
  if (socket.value) {
    socket.value.emit('choose_normal_consensus', {
      sessionId,
      nodeId
    })
  }
  
  ElMessage.success('已选择正常共识，机器人将代替您执行PBFT流程')
}

const chooseByzantineAttack = () => {
  hasChosenAction.value = true
  isNormalMode.value = false
  
  // 通知后端，这个节点选择拜占庭攻击模式
  if (socket.value) {
    socket.value.emit('choose_byzantine_attack', {
      sessionId,
      nodeId
    })
  }
  
  ElMessage.warning('已选择拜占庭攻击模式，您可以发送错误信息')
}

const sendErrorMessage = () => {
  if (!hasChosenAction.value || isNormalMode.value) {
    ElMessage.error('请先选择拜占庭攻击模式')
    return
  }
  
  if (socket.value) {
    // 发送与当前共识值相反的错误信息
    const errorValue = acceptedValue.value === 0 ? 1 : 0
    const errorMessage = {
      sessionId,
      nodeId,
      value: errorValue,
      byzantine: true
    }
    
    // 根据当前阶段发送相应的错误消息
    if (currentPhase.value === 'prepare') {
      socket.value.emit('send_prepare', errorMessage)
    } else if (currentPhase.value === 'commit') {
      socket.value.emit('send_commit', errorMessage)
    }
    
    ElMessage.warning(`🦹 发送错误信息: ${errorValue}`)
  }
}

const sendPrepare = () => {
  if (socket.value) {
    const message = {
      sessionId,
      nodeId,
      value: acceptedValue.value
    }
    socket.value.emit('send_prepare', message)
  }
}

const sendCommit = () => {
  if (socket.value) {
    const message = {
      sessionId,
      nodeId,
      value: acceptedValue.value
    }
    socket.value.emit('send_commit', message)
  }
}

const getPhasePercentage = () => {
  return Math.round((phaseStep.value / 4) * 100)
}

const getPhaseStatus = () => {
  if (phaseStep.value === 4) return 'success'
  if (phaseStep.value > 0) return 'warning'
  return ''
}

const getPhaseDisplayName = (phase) => {
  const names = {
    'new-view': 'New-View 阶段',
    'pre-prepare': 'Prepare 阶段', // 兼容旧命名
    'prepare': 'Prepare 阶段',
    'pre-commit': 'Pre-Commit 阶段',
    'commit': 'Commit 阶段',
    'decide': 'Decide 阶段',
    'reply': 'Decide 阶段' // 兼容旧命名
  }
  return names[phase] || phase
}

const getMessageTypeName = (type) => {
  const names = {
    'pre-prepare': '提议',
    'prepare': '准备',
    'commit': '提交',
    'reply': '回复'
  }
  return names[type] || type
}

const getAcceptedContentDisplay = () => {
  const proposalContent = sessionConfig.value.proposalContent
  const currentAcceptedValue = acceptedValue.value
  
  console.log('getAcceptedContentDisplay called:', {
    acceptedValue: currentAcceptedValue,
    proposalContent: proposalContent,
    proposalContentType: typeof proposalContent,
    proposalContentLength: proposalContent ? proposalContent.length : 0,
    hasProposalContent: proposalContent && proposalContent.trim(),
    sessionConfig: sessionConfig.value
  })
  
  // If there's proposal content, prioritize displaying it
  if (proposalContent && proposalContent.trim()) {
    console.log('Display proposal content:', proposalContent)
    return proposalContent
  }
  
  // If acceptedValue is null, display undecided
  if (currentAcceptedValue === null) {
    console.log('Display undecided')
    return '未决定'
  }
  
  // Otherwise display default Option A/B
  const result = currentAcceptedValue === 0 ? '选项A' : '选项B'
  console.log('Display default option:', result)
  return result
}

const formatTime = (timestamp) => {
  return new Date(timestamp).toLocaleTimeString()
}

const exportMessages = () => {
  const data = receivedMessages.value.map(msg => ({
    Time: formatTime(msg.timestamp),
    来源: `参与者${msg.from}`,
    类型: getMessageTypeName(msg.type),
    内容: msg.value === -1 ? '拒绝' : (msg.value !== null ? (msg.value === 0 ? (sessionConfig.value.proposalContent || '选项A') : (sessionConfig.value.proposalContent || '选项B')) : '无')
  }))
  
  const csv = [
    Object.keys(data[0]).join(','),
    ...data.map(row => Object.values(row).join(','))
  ].join('\n')
  
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `messages_${sessionId}_${nodeId}.csv`
  a.click()
  window.URL.revokeObjectURL(url)
  
  ElMessage.success('消息已导出')
}

const clearMessages = () => {
  receivedMessages.value = []
  ElMessage.success('消息已清除')
}

const refreshTopology = () => {
  topologyConnections.value = []
  
  // Generate connections based on topology
  if (sessionConfig.value.topology === 'full') {
    for (let i = 0; i < sessionConfig.value.nodeCount; i++) {
      for (let j = i + 1; j < sessionConfig.value.nodeCount; j++) {
        // Calculate node center position
        const nodeSize = 40
        const x1 = getNodeX(i) + nodeSize / 2
        const y1 = getNodeY(i) + nodeSize / 2
        const x2 = getNodeX(j) + nodeSize / 2
        const y2 = getNodeY(j) + nodeSize / 2
        
        topologyConnections.value.push({
          from: i,
          to: j,
          x1: x1,
          y1: y1,
          x2: x2,
          y2: y2,
          active: connectedNodes.value.includes(i) && connectedNodes.value.includes(j)
        })
      }
    }
  }
}

const getNodeX = (nodeId) => {
  const containerWidth = topologyWidth.value
  const radius = Math.min(containerWidth, topologyHeight.value) / 2.2  // Increase radius to bring nodes closer to edge
  const nodeSize = 40  // Node size
  
  if (sessionConfig.value.topology === 'full' || sessionConfig.value.topology === 'ring') {
    const angle = (2 * Math.PI * nodeId) / sessionConfig.value.nodeCount
    const centerX = containerWidth / 2 + radius * Math.cos(angle)
    // Adjust position to center-align nodes
    return centerX - nodeSize / 2
  }
  
  return (containerWidth / (sessionConfig.value.nodeCount + 1)) * (nodeId + 1) - nodeSize / 2
}

const getNodeY = (nodeId) => {
  const containerHeight = topologyHeight.value
  const radius = Math.min(topologyWidth.value, containerHeight) / 2.2  // Increase radius to bring nodes closer to edge
  const nodeSize = 40  // Node size
  
  if (sessionConfig.value.topology === 'full' || sessionConfig.value.topology === 'ring') {
    const angle = (2 * Math.PI * nodeId) / sessionConfig.value.nodeCount
    const centerY = containerHeight / 2 + radius * Math.sin(angle)
    // Adjust position to center-align nodes
    return centerY - nodeSize / 2
  }
  
  return containerHeight / 2 - nodeSize / 2
}

const isNodeVisible = (nodeId) => {
  return connectedNodes.value.includes(nodeId)
}

const isNodeActive = (nodeId) => {
  return connectedNodes.value.includes(nodeId)
}

const hasNodeMessages = (nodeId) => {
  return receivedMessages.value.some(msg => msg.from === nodeId)
}

const getNodeMessageCount = (nodeId) => {
  return receivedMessages.value.filter(msg => msg.from === nodeId).length
}

const getNodeMessages = (nodeId) => {
  return receivedMessages.value.filter(msg => msg.from === nodeId)
}

const showNodeDetails = (nodeId) => {
  selectedNode.value = nodeId
  nodeDetailsVisible.value = true
}

const getTopologyName = (topology) => {
  const names = {
    full: '全连接',
    ring: '环形',
    star: '星形',
    tree: '树形'
  }
  return names[topology] || topology
}

const getActiveConnections = () => {
  return topologyConnections.value.filter(conn => conn.active).length
}

// Consensus result display function
const showConsensusResult = () => {
  console.log('显示共识结果')
  
  // 根据当前阶段和状态模拟不同的共识结果
  let result
  
  if (currentPhase.value === 'prepare') {
    result = {
      status: '准备阶段未完成',
      description: '准备阶段需要更多节点参与',
      stats: {
        expected_nodes: sessionConfig.value.nodeCount,
        expected_prepare_nodes: sessionConfig.value.nodeCount - 1,
        total_messages: receivedMessages.value.length
      }
    }
  } else if (currentPhase.value === 'commit') {
    // 根据实际接收到的消息分析共识结果
    const commitMessages = receivedMessages.value.filter(msg => msg.type === 'commit')
    const correctMessages = commitMessages.filter(msg => msg.value === 0).length
    const errorMessages = commitMessages.filter(msg => msg.value === 1).length
    
    // 计算故障节点数 f = floor((n-1)/3)
    const n = sessionConfig.value.nodeCount
    const f = Math.floor((n - 1) / 3)
    const requiredCorrect = 2 * f + 1
    const requiredError = f + 1
    
    console.log(`提交阶段分析 - 总节点数: ${n}, 故障节点数: ${f}`)
    console.log(`提交阶段分析 - 正确消息: ${correctMessages}, 错误消息: ${errorMessages}`)
    console.log(`提交阶段分析 - 需要正确消息: ${requiredCorrect}, 需要错误消息: ${requiredError}`)
    
    if (correctMessages >= requiredCorrect) {
      result = {
        status: '共识成功',
        description: `收到${correctMessages}个正确消息（需要${requiredCorrect}个）`,
        stats: {
          expected_nodes: sessionConfig.value.nodeCount,
          expected_prepare_nodes: sessionConfig.value.nodeCount - 1,
          total_messages: receivedMessages.value.length
        }
      }
    } else if (errorMessages >= requiredError) {
      result = {
        status: '共识失败',
        description: `收到${errorMessages}个错误消息（需要${requiredError}个）`,
        stats: {
          expected_nodes: sessionConfig.value.nodeCount,
          expected_prepare_nodes: sessionConfig.value.nodeCount - 1,
          total_messages: receivedMessages.value.length
        }
      }
    } else {
      result = {
        status: '提交阶段等待中',
        description: `正确消息: ${correctMessages}, 错误消息: ${errorMessages}，等待更多消息`,
        stats: {
          expected_nodes: sessionConfig.value.nodeCount,
          expected_prepare_nodes: sessionConfig.value.nodeCount - 1,
          total_messages: receivedMessages.value.length
        }
      }
    }
  } else if (currentPhase.value === 'completed') {
    result = {
      status: '共识已完成',
      description: '共识过程已经完成',
      stats: {
        expected_nodes: sessionConfig.value.nodeCount,
        expected_prepare_nodes: sessionConfig.value.nodeCount - 1,
        total_messages: receivedMessages.value.length
      }
    }
  } else {
    result = {
      status: '提议阶段',
      description: '正在等待提议',
      stats: {
        expected_nodes: sessionConfig.value.nodeCount,
        expected_prepare_nodes: sessionConfig.value.nodeCount - 1,
        total_messages: receivedMessages.value.length
      }
    }
  }
  
  // 直接调用事件处理函数
  console.log('收到共识结果:', result)
  console.log('共识结果状态:', result.status)
  console.log('共识结果描述:', result.description)
  
  // 根据共识结果显示不同的消息
  if (result.status === '共识成功') {
    console.log('显示成功消息')
    ElMessage.success(`共识成功: ${result.description}`)
  } else if (result.status === '共识失败') {
    console.log('显示失败消息')
    ElMessage.error(`共识失败: ${result.description}`)
  } else if (result.status === '拒绝提议') {
    console.log('显示拒绝消息')
    ElMessage.warning(`拒绝提议: ${result.description}`)
  } else if (result.status === '无诚实节点') {
    console.log('显示无诚实节点消息')
    ElMessage.error(`无诚实节点: ${result.description}`)
  } else {
    console.log('显示其他消息')
    ElMessage.info(`共识结果: ${result.status} - ${result.description}`)
  }
}



const isMyTurn = computed(() => {
  // Only non-proposer nodes (validators) should show validator quick actions
  if (nodeId === 0) {
    return false  // Proposer should not show validator quick actions
  }
  return currentPhase.value === 'prepare' || currentPhase.value === 'commit'
})

// Whether proposer can send messages
const canProposerSendCustom = computed(() => {
  return nodeId === 0
})


// Message sending related methods (custom message functionality removed)


// Lifecycle
onMounted(() => {
  connectToServer()
})

onUnmounted(() => {
  if (socket.value) {
    socket.value.disconnect()
  }
})
</script>

<style scoped>
.node-page {
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.header {
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.2);
  padding: 0 20px;
}

.header-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  height: 100%;
  color: white;
}

.node-info h2 {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 300;
}

.session-info {
  display: flex;
  align-items: center;
  gap: 15px;
}

.main-content {
  padding: 20px;
}

.progress-card, .messages-card, .topology-card {
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 15px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
  height: 100%;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
  color: #2c3e50;
}

.consensus-progress {
  padding: 10px 0;
}

.phase-progress {
  margin-bottom: 20px;
}

.phase-steps {
  margin-top: 15px;
}

.current-status {
  margin-bottom: 20px;
}

.current-status h4 {
  margin-bottom: 10px;
  color: #2c3e50;
}

.quick-actions {
  margin-top: 20px;
}

.quick-actions h4 {
  margin-bottom: 10px;
  color: #2c3e50;
}

.quick-actions-buttons {
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: stretch;
}

.quick-action-btn {
  width: 100%;
  text-align: center;
  justify-content: center;
  display: flex;
  align-items: center;
  height: 40px;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 500;
  border: none;
  box-sizing: border-box;
  margin: 0;
  padding: 0 16px;
  line-height: 1;
  vertical-align: middle;
}

/* 确保两个按钮的尺寸完全一致 */
.quick-actions-buttons .el-button {
  height: 40px !important;
  min-height: 40px !important;
  max-height: 40px !important;
  border-radius: 6px !important;
  font-size: 14px !important;
  font-weight: 500 !important;
  padding: 0 16px !important;
  margin: 0 !important;
  box-sizing: border-box !important;
}

.proposer-info {
  margin-top: 10px;
  text-align: center;
}

/* Byzantine node identifier */
.node-info h2.bad-node {
  color: #f56c6c;
  position: relative;
}

.node-info h2.bad-node::after {
  content: '🦹';
  position: absolute;
  right: -25px;
  top: 0;
  font-size: 16px;
}

/* Message sending form */
.message-form {
  margin-top: 20px;
  padding-top: 20px;
  border-top: 1px solid #e4e7ed;
}

.message-form h4 {
  margin-bottom: 15px;
  color: #2c3e50;
}

.form-tip {
  margin-left: 10px;
  color: #909399;
  font-size: 12px;
}

/* Attack control area styles */
.attack-control {
  margin-top: 20px;
  padding: 15px;
  border: 2px solid #f56c6c;
  border-radius: 8px;
  background: linear-gradient(135deg, #fff5f5 0%, #fef0f0 100%);
  position: relative;
}

.simple-attack-control {
  text-align: center;
}

.attack-tip {
  margin-top: 10px;
}

.attack-control::before {
  content: '⚠️';
  position: absolute;
  top: -10px;
  left: 15px;
  background: #fff;
  padding: 0 8px;
  font-size: 16px;
}

.attack-control h4 {
  color: #f56c6c;
  margin: 0 0 15px 0;
  font-weight: bold;
}

.attack-control .el-form-item {
  margin-bottom: 12px;
}

.attack-control .el-slider {
  margin-top: 5px;
}

.attack-control .el-radio-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.attack-stats {
  margin-top: 15px;
  padding: 10px;
  background: rgba(245, 108, 108, 0.1);
  border-radius: 4px;
  border-left: 3px solid #f56c6c;
}

.attack-stats h5 {
  margin: 0 0 10px 0;
  font-size: 13px;
}

.attack-stats .el-descriptions {
  font-size: 12px;
}

.attack-stats .el-descriptions-item__label {
  color: #f56c6c;
  font-weight: bold;
}

.attack-stats .el-descriptions-item__content {
  color: #303133;
  font-weight: bold;
}

.messages-container {
  height: 400px;
  overflow-y: auto;
}

.messages-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 15px;
  font-weight: 600;
  color: #2c3e50;
}

.message-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.message-item-compact {
  background: #f8f9fa;
  border-radius: 8px;
  padding: 10px;
  border-left: 3px solid #409eff;
}

.message-header-compact {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 5px;
  font-size: 12px;
  color: #606266;
}

.message-content-compact {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 13px;
}

.message-type {
  font-weight: 600;
  color: #409eff;
}

.message-value {
  color: #2c3e50;
}

.no-messages {
  text-align: center;
  padding: 40px 0;
}

.dynamic-topology {
  padding: 10px 0;
}

.topology-info {
  margin-bottom: 15px;
  padding: 10px;
  background: #f8f9fa;
  border-radius: 8px;
}

.topology-info p {
  margin: 5px 0;
  font-size: 14px;
  color: #606266;
}

.topology-container {
  position: relative;
  width: 100%;
  height: 400px;
  background: #f8f9fa;
  border-radius: 10px;
  margin-bottom: 20px;
}

.connection-lines {
  position: absolute;
  top: 0;
  left: 0;
  z-index: 1;
}

.active-connection {
  stroke: #67c23a;
  stroke-width: 2;
}

.inactive-connection {
  stroke: #dcdfe6;
  stroke-width: 1;
}

.topology-node {
  position: absolute;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: #409eff;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  cursor: pointer;
  z-index: 2;
  transition: all 0.3s ease;
  border: 2px solid white;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.topology-node:hover {
  transform: scale(1.1);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
}

.topology-node.current-node {
  background: #67c23a;
  border-color: #67c23a;
}

.topology-node.proposer {
  background: #e6a23c;
  border-color: #e6a23c;
}

.topology-node.visible-node {
  opacity: 1;
}

.topology-node.invisible-node {
  opacity: 0.3;
}

.topology-node.has-messages {
  border-color: #f56c6c;
}

.topology-node.active {
  animation: pulse 2s infinite;
}


.node-number {
  font-size: 14px;
  font-weight: 600;
}

.node-status-indicator {
  position: absolute;
  top: -2px;
  right: -2px;
  width: 8px;
  height: 8px;
  background: #67c23a;
  border-radius: 50%;
  border: 1px solid white;
}

.message-count {
  position: absolute;
  top: -8px;
  right: -8px;
  background: #f56c6c;
  color: white;
  border-radius: 50%;
  width: 16px;
  height: 16px;
  font-size: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid white;
}


.node-messages {
  max-height: 300px;
  overflow-y: auto;
}

.message-item {
  background: #f8f9fa;
  border-radius: 8px;
  padding: 10px;
  margin-bottom: 10px;
  border-left: 3px solid #409eff;
}

.message-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 5px;
  font-size: 12px;
  color: #606266;
}

.message-content {
  font-size: 13px;
  color: #2c3e50;
}

@keyframes pulse {
  0% {
    box-shadow: 0 0 0 0 rgba(64, 158, 255, 0.7);
  }
  70% {
    box-shadow: 0 0 0 10px rgba(64, 158, 255, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(64, 158, 255, 0);
  }
}

@media (max-width: 768px) {
  .main-content {
    padding: 10px;
  }
  
  .header-content {
    flex-direction: column;
    gap: 10px;
  }
  
  .node-info h2 {
    font-size: 1.2rem;
  }
}
</style> 