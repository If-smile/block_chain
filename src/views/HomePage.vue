<template>
  <div class="dashboard-page">
    <!-- 顶部统计卡片 -->
    <el-row :gutter="16" class="metrics-row">
      <el-col :span="6">
        <el-card shadow="never" class="metric-card">
          <div class="metric-content">
            <div class="metric-icon primary-bg">
              <el-icon :size="32"><Connection /></el-icon>
            </div>
            <div class="metric-info">
              <div class="metric-label">Total Nodes</div>
              <div class="metric-value">{{ formData.nodeCount }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
      
      <el-col :span="6">
        <el-card shadow="never" class="metric-card">
          <div class="metric-content">
            <div class="metric-icon danger-bg">
              <el-icon :size="32"><WarnTriangleFilled /></el-icon>
            </div>
            <div class="metric-info">
              <div class="metric-label">Byzantine Nodes</div>
              <div class="metric-value">{{ formData.faultyNodes }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
      
      <el-col :span="6">
        <el-card shadow="never" class="metric-card">
          <div class="metric-content">
            <div class="metric-icon success-bg">
              <el-icon :size="32"><Cpu /></el-icon>
            </div>
            <div class="metric-info">
              <div class="metric-label">Consensus Health</div>
              <div class="metric-value">{{ consensusHealth }}%</div>
            </div>
          </div>
        </el-card>
      </el-col>
      
      <el-col :span="6">
        <el-card shadow="never" class="metric-card">
          <div class="metric-content">
            <div class="metric-icon warning-bg">
              <el-icon :size="32"><Grid /></el-icon>
            </div>
            <div class="metric-info">
              <div class="metric-label">Network Groups</div>
              <div class="metric-value">{{ formData.branchCount }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
    
    <!-- 主内容区域：配置表单 + 拓扑预览 -->
    <el-row :gutter="16" class="main-row">
      <!-- 左侧：创世配置 -->
      <el-col :span="8">
        <el-card shadow="never" class="config-card">
          <template #header>
            <div class="section-header">
              <div class="header-line"></div>
              <span class="header-title">Genesis Configuration</span>
            </div>
          </template>
          
          <el-form 
            :model="formData" 
            :rules="rules" 
            ref="formRef" 
            label-width="140px"
            label-position="left"
            class="genesis-form"
            size="default"
          >
            <el-form-item label="Node Count" prop="nodeCount">
              <el-input-number 
                v-model="formData.nodeCount" 
                :min="3" 
                :max="20"
                controls-position="right"
                class="full-width"
              />
            </el-form-item>
            
            <el-form-item label="Faulty Nodes" prop="faultyNodes">
              <el-input-number 
                v-model="formData.faultyNodes" 
                :min="0" 
                :max="formData.nodeCount"
                controls-position="right"
                class="full-width"
              />
            </el-form-item>
            
            <el-form-item label="Topology" prop="topology">
              <el-select v-model="formData.topology" class="full-width">
                <el-option label="Full Mesh" value="full" />
                <el-option label="Ring" value="ring" />
                <el-option label="Star" value="star" />
                <el-option label="Tree" value="tree" />
              </el-select>
            </el-form-item>
            
            <el-form-item label="Branch Count" prop="branchCount">
              <el-input-number 
                v-model="formData.branchCount" 
                :min="1" 
                :max="10"
                controls-position="right"
                class="full-width"
              />
            </el-form-item>
            
            <el-form-item label="Proposal Value" prop="proposalValue">
              <el-radio-group v-model="formData.proposalValue">
                <el-radio :label="0">0</el-radio>
                <el-radio :label="1">1</el-radio>
              </el-radio-group>
            </el-form-item>
            
            <el-form-item label="Proposal Content" prop="proposalContent">
              <el-input 
                v-model="formData.proposalContent" 
                type="textarea" 
                :rows="2"
                placeholder="Enter proposal content..."
              />
            </el-form-item>
            
            <el-form-item label="Malicious Leader">
              <el-switch v-model="formData.maliciousProposer" />
            </el-form-item>
            
            <el-form-item label="Allow Tampering">
              <el-switch v-model="formData.allowTampering" />
            </el-form-item>
            
            <el-form-item label="Delivery Rate">
              <el-slider 
                v-model="formData.messageDeliveryRate" 
                :min="50" 
                :max="100" 
                :step="5"
                show-input
                :format-tooltip="(val) => `${val}%`"
              />
            </el-form-item>
            
            <el-form-item class="action-buttons">
              <el-button 
                type="primary" 
                @click="createSession" 
                :loading="creating"
                style="width: 100%; margin-bottom: 8px;"
              >
                Create Session
              </el-button>
              <el-button 
                type="success" 
                @click="showDemo" 
                :loading="simulating"
                style="width: 100%; margin-bottom: 8px;"
              >
                <el-icon style="margin-right: 5px;"><VideoPlay /></el-icon>
                Demo Animation
              </el-button>
              <el-button 
                @click="resetForm"
                style="width: 100%;"
              >
                Reset
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
      
      <!-- 右侧：网络拓扑预览 -->
      <el-col :span="16">
        <el-card shadow="never" class="preview-card">
          <template #header>
            <div class="section-header">
              <div class="header-line"></div>
              <span class="header-title">Network Topology Preview</span>
            </div>
          </template>
          
          <div class="topology-preview">
            <Topology
              :topologyType="formData.topology"
              :nodeCount="formData.nodeCount"
              :byzantineNodes="formData.faultyNodes"
              :simulationResult="null"
              :proposalValue="formData.proposalValue"
              :currentLeader="0"
              :branchCount="formData.branchCount"
            />
          </div>
        </el-card>
      </el-col>
    </el-row>
    
    <!-- 会话信息与接入点 (Session Created) -->
    <el-row :gutter="16" v-if="sessionInfo" class="session-row">
      <el-col :span="24">
        <el-alert
          type="success"
          :closable="false"
          class="session-alert"
        >
          <template #title>
            <div class="alert-title">
              <el-icon :size="20"><SuccessFilled /></el-icon>
              <span>Session Created Successfully - ID: {{ sessionInfo.sessionId }}</span>
            </div>
          </template>
        </el-alert>
      </el-col>
      
      <!-- 会话详情 -->
      <el-col :span="16">
        <el-card shadow="never" class="access-card">
          <template #header>
            <div class="section-header">
              <div class="header-line"></div>
              <span class="header-title">Access Points</span>
            </div>
          </template>
          
          <div class="access-content">
            <el-table 
              :data="nodeLinks" 
              stripe
              class="access-table"
              :header-cell-style="{ background: '#fafafa', color: '#606266', fontWeight: 600 }"
            >
              <el-table-column prop="nodeId" label="Node ID" width="100" align="center">
                <template #default="{ row }">
                  <el-tag size="small" type="info">Node {{ row.nodeId }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="url" label="Access URL">
                <template #default="{ row }">
                  <code class="url-text">{{ row.url }}</code>
                </template>
              </el-table-column>
              <el-table-column label="Actions" width="140" align="center">
                <template #default="{ row }">
                  <el-button size="small" type="primary" @click="copyLink(row.url)" plain>
                    <el-icon><CopyDocument /></el-icon>
                    Copy
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-card>
      </el-col>
      
      <!-- 二维码 -->
      <el-col :span="8">
        <el-card shadow="never" class="qr-card">
          <template #header>
            <div class="section-header">
              <div class="header-line"></div>
              <span class="header-title">Quick Join (QR Code)</span>
            </div>
          </template>
          
          <div class="qr-content">
            <div class="qr-container" ref="qrContainer"></div>
            <p class="qr-tip">Scan to join consensus network</p>
          </div>
        </el-card>
      </el-col>
    </el-row>
    
    <!-- 动画演示对话框 -->
    <el-dialog
      v-model="demoDialogVisible"
      title="Consensus Process Animation"
      width="90%"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <div class="demo-container">
        <div class="round-selector">
          <el-tag type="success" size="large">Real Session History</el-tag>
          <el-divider direction="vertical" v-if="simulationRounds.length > 1" />
          <span v-if="simulationRounds.length > 1" class="round-label">Select Round:</span>
          <el-radio-group v-if="simulationRounds.length > 1" v-model="currentRound" @change="onRoundChange">
            <el-radio-button 
              v-for="round in simulationRounds" 
              :key="round.id" 
              :label="round.id"
            >
              Round {{ round.id }}
            </el-radio-button>
          </el-radio-group>
          <el-button 
            type="primary" 
            @click="playAnimation" 
            :disabled="!currentSimulation"
            style="margin-left: auto;"
          >
            <el-icon><VideoPlay /></el-icon>
            Replay
          </el-button>
        </div>
        
        <div class="demo-content">
          <div class="topology-section">
            <Topology
              v-if="currentSimulation"
              ref="topologyRef"
              :topologyType="sessionInfo?.config?.topology || formData.topology"
              :nodeCount="sessionInfo?.config?.nodeCount || formData.nodeCount"
              :byzantineNodes="sessionInfo?.config?.faultyNodes || formData.faultyNodes"
              :branchCount="sessionInfo?.config?.branchCount || formData.branchCount"
              :proposalValue="sessionInfo?.config?.proposalValue || formData.proposalValue"
              :simulationResult="currentSimulation"
              :currentLeader="demoLeader"
            />
          </div>
          
          <div class="table-section">
            <HotStuffTable
              v-if="currentSimulation"
              :simulationResult="currentSimulation"
              :nodeCount="sessionInfo?.config?.nodeCount || formData.nodeCount"
            />
          </div>
        </div>
      </div>
      
      <template #footer>
        <el-button @click="demoDialogVisible = false">Close</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script>
import { ref, reactive, computed, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { 
  VideoPlay, 
  Connection, 
  WarnTriangleFilled, 
  Cpu, 
  Grid, 
  SuccessFilled,
  CopyDocument 
} from '@element-plus/icons-vue'
import QRCode from 'qrcode'
import axios from 'axios'
import Topology from '@/components/Topology.vue'
import HotStuffTable from '@/components/HotStuffTable.vue'

export default {
  name: 'HomePage',
  components: {
    VideoPlay,
    Connection,
    WarnTriangleFilled,
    Cpu,
    Grid,
    SuccessFilled,
    CopyDocument,
    Topology,
    HotStuffTable
  },
  setup() {
    const formRef = ref(null)
    const qrContainer = ref(null)
    const creating = ref(false)
    const sessionInfo = ref(null)
    
    const demoDialogVisible = ref(false)
    const simulating = ref(false)
    const simulationRounds = ref([])
    const currentRound = ref(1)
    const currentSimulation = ref(null)
    const topologyRef = ref(null)
    
    const formData = reactive({
      nodeCount: 20,
      faultyNodes: 1,
      topology: 'full',
      branchCount: 4,
      proposalValue: 0,
      proposalContent: '',
      maliciousProposer: false,
      allowTampering: false,
      messageDeliveryRate: 100
    })
    
    const rules = {
      nodeCount: [
        { required: true, message: 'Please enter node count', trigger: 'blur' }
      ],
      faultyNodes: [
        { required: true, message: 'Please enter faulty nodes', trigger: 'blur' }
      ],
      topology: [
        { required: true, message: 'Please select topology', trigger: 'change' }
      ]
    }
    
    const consensusHealth = computed(() => {
      const deliveryRate = formData.messageDeliveryRate
      const faultyRatio = formData.faultyNodes / formData.nodeCount
      return Math.round(deliveryRate * (1 - faultyRatio * 0.5))
    })
    
    const currentView = computed(() => sessionInfo.value?.currentView ?? 0)
    const currentLeader = computed(() => sessionInfo.value?.leaderId ?? 0)
    
    const nodeLinks = computed(() => {
      if (!sessionInfo.value) return []
      
      const links = []
      const robotNodes = sessionInfo.value.config.robotNodes || 0
      const humanNodeCount = sessionInfo.value.config.nodeCount - robotNodes
      
      for (let i = 0; i < humanNodeCount; i++) {
        const nodeId = robotNodes + i
        links.push({
          nodeId: nodeId,
          url: `${window.location.origin}/node/${sessionInfo.value.sessionId}/${nodeId}`
        })
      }
      return links
    })
    
    const createSession = async () => {
      try {
        await formRef.value.validate()
        creating.value = true
        
        const response = await axios.post('/api/sessions', {
          nodeCount: formData.nodeCount,
          faultyNodes: formData.faultyNodes,
          robotNodes: formData.nodeCount - formData.faultyNodes,
          topology: formData.topology,
          branchCount: formData.branchCount,
          proposalValue: formData.proposalValue,
          proposalContent: formData.proposalContent,
          maliciousProposer: formData.maliciousProposer,
          allowTampering: formData.allowTampering,
          messageDeliveryRate: formData.messageDeliveryRate
        })
        
        sessionInfo.value = response.data
        ElMessage.success('Session created successfully!')
      } catch (error) {
        console.error('Failed to create session:', error)
        ElMessage.error('Failed to create session')
      } finally {
        creating.value = false
      }
    }
    
    const generateQRCode = async () => {
      if (!qrContainer.value || !sessionInfo.value) return
      
      try {
        qrContainer.value.innerHTML = ''
        
        const qrData = {
          sessionId: sessionInfo.value.sessionId,
          nodeCount: sessionInfo.value.config.nodeCount,
          joinUrl: `${window.location.origin}/join/${sessionInfo.value.sessionId}`,
          autoAssign: true
        }
        
        try {
          await QRCode.toCanvas(qrContainer.value, JSON.stringify(qrData), {
            width: 180,
            margin: 2
          })
          return
        } catch (error1) {
          const canvas = document.createElement('canvas')
          qrContainer.value.appendChild(canvas)
          await QRCode.toCanvas(canvas, JSON.stringify(qrData), {
            width: 180,
            margin: 2
          })
        }
      } catch (error) {
        console.error('Failed to generate QR code:', error)
        qrContainer.value.innerHTML = `
          <div style="color: #f56c6c; padding: 20px; text-align: center;">
            QR code generation failed
          </div>
        `
      }
    }
    
    const copyLink = async (url) => {
      try {
        await navigator.clipboard.writeText(url)
        ElMessage.success('Link copied to clipboard')
      } catch (error) {
        ElMessage.error('Copy failed')
      }
    }
    
    const resetForm = () => {
      formRef.value.resetFields()
      sessionInfo.value = null
    }
    
    watch(sessionInfo, async (newSessionInfo) => {
      if (newSessionInfo) {
        await new Promise(resolve => setTimeout(resolve, 100))
        await generateQRCode()
      }
    })
    
    const showDemo = async () => {
      try {
        simulating.value = true
        
        if (!sessionInfo.value) {
          ElMessage.error('Please create a session first!')
          return
        }
        
        simulationRounds.value = []
        
        const roundsResponse = await axios.get(`/api/sessions/${sessionInfo.value.sessionId}/history`)
        const rounds = roundsResponse.data.rounds || [1]
        
        for (const roundNum of rounds) {
          const response = await axios.get(`/api/sessions/${sessionInfo.value.sessionId}/history?round=${roundNum}`)
          const roundData = response.data || {}
          const leaderId =
            typeof roundData.leaderId === 'number'
              ? roundData.leaderId
              : ((roundNum - 1 + (roundData.nodeCount || sessionInfo.value?.config?.nodeCount || formData.nodeCount)) % (roundData.nodeCount || sessionInfo.value?.config?.nodeCount || formData.nodeCount))
          simulationRounds.value.push({
            id: roundNum,
            data: { ...roundData, leaderId },
            isReal: true
          })
        }
        
        // 默认选中最新的一轮（最后一轮）
        const latestRound = rounds.length > 0 ? rounds[rounds.length - 1] : rounds[0] || 1
        currentRound.value = latestRound
        const latestRoundData = simulationRounds.value.find(r => r.id === latestRound)
        currentSimulation.value = latestRoundData ? latestRoundData.data : (simulationRounds.value[0]?.data || null)
        
        demoDialogVisible.value = true
        
        await nextTick()
        await new Promise(resolve => setTimeout(resolve, 300))
        playAnimation()
        
        ElMessage.success(`Loaded ${rounds.length} consensus rounds`)
      } catch (error) {
        console.error('Failed to get session history:', error)
        ElMessage.error('Failed to load session history')
      } finally {
        simulating.value = false
      }
    }
    
    const onRoundChange = (roundId) => {
      const round = simulationRounds.value.find(r => r.id === roundId)
      if (round) {
        currentSimulation.value = round.data
        nextTick(() => {
          playAnimation()
        })
      }
    }
    
    const demoLeader = computed(() => {
      if (currentSimulation.value && typeof currentSimulation.value.leaderId === 'number') {
        return currentSimulation.value.leaderId
      }
      return currentLeader.value ?? 0
    })
    
    const playAnimation = () => {
      if (topologyRef.value && topologyRef.value.startAnimation) {
        topologyRef.value.startAnimation()
      }
    }
    
    return {
      formRef,
      qrContainer,
      creating,
      sessionInfo,
      formData,
      rules,
      consensusHealth,
      nodeLinks,
      createSession,
      copyLink,
      resetForm,
      demoDialogVisible,
      simulating,
      simulationRounds,
      currentRound,
      currentSimulation,
      topologyRef,
      showDemo,
      onRoundChange,
      playAnimation,
      demoLeader
    }
  }
}
</script>

<style scoped>
.dashboard-page {
  padding: 0;
  min-height: calc(100vh - 64px);
}

/* ========== 统计卡片 ========== */
.metrics-row {
  margin-bottom: 16px;
}

.metric-card {
  border-radius: 8px;
  border: 1px solid #e8e8e8;
  transition: all 0.3s;
}

.metric-card:hover {
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
  transform: translateY(-2px);
}

.metric-content {
  display: flex;
  align-items: center;
  gap: 16px;
}

.metric-icon {
  width: 56px;
  height: 56px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.primary-bg {
  background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%);
  color: #1976d2;
}

.danger-bg {
  background: linear-gradient(135deg, #ffebee 0%, #ffcdd2 100%);
  color: #d32f2f;
}

.success-bg {
  background: linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%);
  color: #388e3c;
}

.warning-bg {
  background: linear-gradient(135deg, #fff3e0 0%, #ffe0b2 100%);
  color: #f57c00;
}

.metric-info {
  flex: 1;
}

.metric-label {
  font-size: 14px;
  color: #606266;
  margin-bottom: 4px;
}

.metric-value {
  font-size: 24px;
  font-weight: 700;
  color: #303133;
  line-height: 1;
}

/* ========== 主内容区域 ========== */
.main-row {
  margin-bottom: 16px;
}

.config-card,
.preview-card,
.access-card,
.qr-card {
  border-radius: 8px;
  border: 1px solid #e8e8e8;
  min-height: 600px;
}

/* Section Header (Vben 风格) */
.section-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-line {
  width: 3px;
  height: 16px;
  background: #1890ff;
  border-radius: 2px;
}

.header-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

/* ========== 配置表单 ========== */
.genesis-form {
  padding: 8px 0;
}

.genesis-form :deep(.el-form-item) {
  margin-bottom: 20px;
}

.genesis-form :deep(.el-form-item__label) {
  font-size: 13px;
  color: #606266;
  font-weight: 500;
}

.full-width {
  width: 100%;
}

.action-buttons {
  margin-top: 24px;
  margin-bottom: 0;
}

.action-buttons :deep(.el-form-item__content) {
  display: flex;
  flex-direction: column;
}

/* ========== 拓扑预览 ========== */
.topology-preview {
  min-height: 500px;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* ========== 会话区域 ========== */
.session-row {
  margin-bottom: 16px;
}

.session-alert {
  border-radius: 8px;
  margin-bottom: 16px;
}

.alert-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
}

/* ========== 接入点表格 (Etherscan 风格) ========== */
.access-content {
  padding: 0;
}

.access-table {
  font-size: 13px;
}

.access-table :deep(th) {
  padding: 12px 0;
}

.access-table :deep(td) {
  padding: 10px 0;
}

.url-text {
  font-family: 'JetBrains Mono', 'Roboto Mono', 'Courier New', monospace;
  font-size: 12px;
  background: #f5f5f5;
  padding: 4px 8px;
  border-radius: 4px;
  color: #1890ff;
}

/* ========== 二维码 ========== */
.qr-card {
  min-height: auto;
}

.qr-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 20px 0;
}

.qr-container {
  padding: 16px;
  background: #fff;
  border: 2px solid #e8e8e8;
  border-radius: 8px;
  display: inline-block;
}

.qr-tip {
  margin-top: 16px;
  font-size: 13px;
  color: #909399;
  text-align: center;
}

/* ========== 动画演示对话框 ========== */
.demo-container {
  padding: 16px;
}

.round-selector {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px;
  background: #fafafa;
  border-radius: 8px;
  margin-bottom: 20px;
}

.round-label {
  font-size: 14px;
  font-weight: 500;
  color: #606266;
}

.demo-content {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.topology-section,
.table-section {
  background: #fff;
  border-radius: 8px;
}

/* ========== 响应式 ========== */
@media (max-width: 1200px) {
  .metric-value {
    font-size: 20px;
  }
  
  .metric-icon {
    width: 48px;
    height: 48px;
  }
}

@media (max-width: 768px) {
  .metrics-row .el-col {
    margin-bottom: 12px;
  }
}
</style>
