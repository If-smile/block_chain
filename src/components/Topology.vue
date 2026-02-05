<template>
  <el-card class="topology-container" shadow="hover">
    <!-- Card Header with Icon and Legend -->
    <template #header>
      <div class="topology-header">
        <div class="header-left">
          <el-icon :size="24" class="header-icon">
            <Connection />
          </el-icon>
          <span class="header-title">Network Topology Monitor</span>
        </div>
        
        <!-- Node Status Legend -->
        <div class="legend-container">
          <div class="legend-item">
            <span class="legend-dot root-dot"></span>
            <span class="legend-label">Root Leader</span>
          </div>
          <div class="legend-item">
            <span class="legend-dot group-leader-dot"></span>
            <span class="legend-label">Group Leader</span>
          </div>
          <div class="legend-item">
            <span class="legend-dot member-dot"></span>
            <span class="legend-label">Member</span>
          </div>
          <div class="legend-item">
            <span class="legend-dot byzantine-dot"></span>
            <span class="legend-label">Byzantine</span>
          </div>
        </div>
      </div>
    </template>
    
    <!-- Canvas Container -->
    <div class="canvas-wrapper">
      <canvas ref="canvas" width="800" height="700"></canvas>
      
      <!-- Consensus Result Overlay with Transition -->
      <transition name="el-fade-in">
        <div v-if="finalConsensus" class="result-overlay">
          <el-result
            icon="success"
            title="Consensus Reached"
            :sub-title="`Final Value: ${finalConsensus}`"
            class="consensus-result"
          >
            <template #icon>
              <el-icon class="result-icon" :size="80">
                <SuccessFilled />
              </el-icon>
            </template>
            <template #extra>
              <el-tag type="success" size="large" effect="dark">
                ✓ Network consensus confirmed
              </el-tag>
            </template>
          </el-result>
        </div>
      </transition>
    </div>
  </el-card>
</template>

<script>
import { ref, computed, onMounted, watch } from "vue";
import { Connection, SuccessFilled } from '@element-plus/icons-vue';

export default {
  components: {
    Connection,
    SuccessFilled
  },
  props: ["topologyType", "nodeCount", "byzantineNodes", "simulationResult", "proposalValue", "currentLeader", "branchCount"],
  setup(props) {
    const canvas = ref(null);
    const ctx = ref(null);
    const finalConsensus = ref("");

    // 1. 类型安全转换
    const safeNodeCount = computed(() => Number(props.nodeCount) || 0);
    const safeBranchCount = computed(() => Number(props.branchCount) || 2);
    const safeCurrentLeader = computed(() => Number(props.currentLeader ?? 0));

    const isDoubleLayer = computed(() => {
      return safeBranchCount.value > 1 && safeNodeCount.value >= safeBranchCount.value * 2;
    });

    // 2. 拓扑角色计算
    const getTopologyInfo = (nodeId) => {
      const n = safeNodeCount.value;
      const branchCount = safeBranchCount.value;
      const globalLeaderId = safeCurrentLeader.value; 
      
      // Root
      if (nodeId === globalLeaderId) {
        return { role: 'root', parentId: null, groupId: Math.floor(nodeId / Math.max(1, Math.floor(n / branchCount))) };
      }
      
      const groupSize = Math.max(1, Math.floor(n / branchCount));
      const groupId = Math.floor(nodeId / groupSize);
      const groupStartId = groupId * groupSize;
      
      // Group Leader
      if (nodeId === groupStartId) {
        return { role: 'group_leader', parentId: globalLeaderId, groupId };
      } 
      
      // Member
      return { role: 'member', parentId: groupStartId, groupId };
    };

    // 3. 布局计算 (保留防重叠逻辑)
    const nodePositions = computed(() => {
      const positions = new Array(safeNodeCount.value).fill(null);
      const n = safeNodeCount.value;
      const branchCount = safeBranchCount.value;
      const globalLeaderId = safeCurrentLeader.value;
      
      // --- 单层模式 ---
      if (!isDoubleLayer.value) {
        const cx = 400, cy = 350, radius = 250;
        for (let i = 0; i < n; i++) {
          const angle = (i / n) * (2 * Math.PI) - (Math.PI / 2);
          positions[i] = {
            x: cx + radius * Math.cos(angle),
            y: cy + radius * Math.sin(angle),
            role: i === globalLeaderId ? 'root' : 'member',
            color: i === globalLeaderId ? '#FFD700' : 'green'
          };
        }
        return positions;
      }

      // --- 双层模式 ---
      const canvasWidth = 800;
      const groupSpacing = canvasWidth / branchCount;
      const groupCenterX = {};
      for(let g=0; g<branchCount; g++) {
        groupCenterX[g] = (g + 0.5) * groupSpacing;
      }

      // Root
      const rootGroupId = Math.floor(globalLeaderId / Math.max(1, Math.floor(n / branchCount)));
      positions[globalLeaderId] = {
        x: 400, 
        y: 80,
        role: 'root',
        color: '#FFD700'
      };

      // Group Leaders
      for (let i = 0; i < n; i++) {
        if (i === globalLeaderId) continue;
        const info = getTopologyInfo(i);
        if (info.role === 'group_leader') {
          positions[i] = {
            x: groupCenterX[info.groupId],
            y: 250,
            role: 'group_leader',
            color: '#4169E1'
          };
        }
      }

      // Members (防重叠)
      const membersByGroup = {};
      for (let i = 0; i < n; i++) {
        if (positions[i]) continue;
        const info = getTopologyInfo(i);
        if (!membersByGroup[info.groupId]) membersByGroup[info.groupId] = [];
        membersByGroup[info.groupId].push(i);
      }

      Object.keys(membersByGroup).forEach(gid => {
        const members = membersByGroup[gid];
        const count = members.length;
        if (count === 0) return;

        const cx = groupCenterX[gid] || 400;
        const groupWidth = groupSpacing;
        const idealSpacing = groupWidth / count;
        const spacing = Math.max(idealSpacing, 35); 
        
        const totalWidth = (count - 1) * spacing;
        const startX = cx - totalWidth / 2;

        members.forEach((nodeId, idx) => {
          positions[nodeId] = {
            x: startX + idx * spacing,
            y: 450,
            role: 'member',
            color: '#32CD32'
          };
        });
      });

      return positions;
    });

    // 4. 绘图逻辑
    const drawTopology = () => {
      if (!ctx.value) return;
      ctx.value.clearRect(0, 0, 800, 700);
      const positions = nodePositions.value;
      const n = safeNodeCount.value;

      if (n === 0 || positions.length === 0) return;

      // 画线
      positions.forEach((pos, i) => {
        if (!pos) return;
        if (isDoubleLayer.value) {
          const info = getTopologyInfo(i);
          if (info.parentId !== null && positions[info.parentId]) {
            const parentPos = positions[info.parentId];
            const isToRoot = parentPos.role === 'root';
            drawLine(parentPos, pos, isToRoot ? "#aaa" : "#ccc", isToRoot ? 2 : 1);
          }
        } else {
          const leaderId = safeCurrentLeader.value;
          if (i !== leaderId && positions[leaderId]) {
            drawLine(positions[leaderId], pos, "#ddd", 1);
          }
        }
      });

      // 画点
      drawNodes();
    };

    const drawNodes = () => {
      const positions = nodePositions.value;
      const byzantineStart = safeNodeCount.value - (Number(props.byzantineNodes) || 0);

      positions.forEach((pos, i) => {
        if (!pos) return;
        ctx.value.beginPath();
        let r = 20;
        if (pos.role === 'root') r = 30;
        else if (pos.role === 'group_leader') r = 25;
        else if (pos.role === 'member') r = 15; 

        ctx.value.arc(pos.x, pos.y, r, 0, Math.PI * 2);
        
        let color = pos.color;
        if (i >= byzantineStart) color = "red";
        
        ctx.value.fillStyle = color;
        ctx.value.fill();
        ctx.value.strokeStyle = "#333";
        ctx.value.lineWidth = 2;
        ctx.value.stroke();

        ctx.value.fillStyle = "white";
        ctx.value.font = "bold 12px Arial";
        ctx.value.textAlign = "center";
        ctx.value.textBaseline = "middle";
        ctx.value.fillText(i, pos.x, pos.y);
      });
    };

    const drawLine = (p1, p2, color, width) => {
      ctx.value.beginPath();
      ctx.value.moveTo(p1.x, p1.y);
      ctx.value.lineTo(p2.x, p2.y);
      ctx.value.strokeStyle = color;
      ctx.value.lineWidth = width;
      ctx.value.stroke();
    };

    // 5. 动画引擎 (关键修复)
    const runAnimation = (messages, doneCallback) => {
       console.log("[runAnimation] 收到消息数组:", messages);
       console.log("[runAnimation] 消息数量:", messages?.length || 0);
       
       const positions = nodePositions.value;
       if (!positions || positions.length === 0) {
           console.log("[runAnimation] 警告: 节点位置为空，跳过动画");
           if(doneCallback) doneCallback(); 
           return;
       }

       const animations = [];
       
       messages.forEach(msg => {
           let targets = [];
           // 解析目标
           if (msg.dst === 'all') {
               targets = positions.map((_,i)=>i).filter(i=>i!==msg.src);
           } else if (msg.dst === 'group_leaders') {
               positions.forEach((p,i)=>{if(p && p.role==='group_leader') targets.push(i)});
           } else if (msg.dst === 'group_members') {
               const srcInfo = getTopologyInfo(msg.src);
               positions.forEach((p,i)=>{
                   const tInfo = getTopologyInfo(i);
                   if(tInfo.groupId === srcInfo.groupId && tInfo.role === 'member') targets.push(i);
               });
           } else {
               targets = [msg.dst];
           }
           
           targets.forEach(dst => {
               if(positions[msg.src] && positions[dst]) {
                   animations.push({
                       start: positions[msg.src],
                       end: positions[dst],
                       progress: 0,
                       value: msg.value
                   });
               }
           });
       });
       
       console.log("[runAnimation] 解析后的动画数量:", animations.length);
       console.log("[runAnimation] 动画详情:", animations.map(a => ({
         from: `${a.start.x},${a.start.y}`,
         to: `${a.end.x},${a.end.y}`,
         value: a.value
       })));
       
       if(!animations.length) { 
           console.log("[runAnimation] 警告: 没有有效的动画目标，跳过播放");
           if(doneCallback) doneCallback(); 
           return; 
       }
       
       console.log(`[runAnimation] 开始播放动画帧: ${animations.length} 个小球`);

       const loop = () => {
           // 1. 清空画布并重绘背景拓扑
           ctx.value.clearRect(0,0,800,700);
           drawTopology();
           
           let active = false;
           // 2. 绘制所有运动的小球
           animations.forEach(a => {
               if(a.progress < 1) {
                   a.progress += 0.02; // 速度控制
                   active = true;
                   
                   const x = a.start.x + (a.end.x - a.start.x) * a.progress;
                   const y = a.start.y + (a.end.y - a.start.y) * a.progress;
                   
                   ctx.value.beginPath();
                   ctx.value.arc(x, y, 8, 0, Math.PI * 2); // 小球半径8
                   
                   // 颜色判定：值匹配则绿，否则红
                   const isCorrect = (a.value == props.proposalValue);
                   ctx.value.fillStyle = isCorrect ? '#32CD32' : 'red';
                   ctx.value.fill();
                   ctx.value.strokeStyle = 'white';
                   ctx.value.stroke();
               }
           });
           
           if(active) {
               requestAnimationFrame(loop);
           } else if(doneCallback) {
               doneCallback();
           }
       }
       loop();
    };

    const playSequence = (seq, idx) => {
        if(!seq || idx >= seq.length) {
            finalConsensus.value = props.simulationResult?.consensus || "Completed";
            return;
        }
        runAnimation(seq[idx], () => playSequence(seq, idx+1));
    };

    const startAnimation = () => {
        console.log("[startAnimation] 被调用");
        console.log("[startAnimation] simulationResult:", props.simulationResult);
        console.log("[startAnimation] animation_sequence:", props.simulationResult?.animation_sequence);
        
        if (props.simulationResult?.animation_sequence) {
            console.log("[startAnimation] 收到共识结果，开始播放序列动画...");
            console.log("[startAnimation] 序列步骤数:", props.simulationResult.animation_sequence.length);
            finalConsensus.value = "";
            playSequence(props.simulationResult.animation_sequence, 0);
        } else {
            console.log("[startAnimation] 警告: animation_sequence 不存在或为空");
        }
    };

    onMounted(() => {
      ctx.value = canvas.value.getContext("2d");
      drawTopology();
    });

    // 使用 deep: true 确保深度监听
    watch(() => props.simulationResult, (newVal, oldVal) => {
        console.log("[watch] simulationResult 变化:", { newVal, oldVal });
        startAnimation();
    }, { deep: true, immediate: false });
    
    watch([() => props.nodeCount, () => props.branchCount], () => {
        console.log("[watch] nodeCount 或 branchCount 变化，重绘拓扑");
        drawTopology();
    });

    return { canvas, finalConsensus, startAnimation };
  }
};
</script>

<style scoped>
/* ========== 容器样式 ========== */
.topology-container {
  width: 100%;
  max-width: 1200px;
  margin: 0 auto;
}

/* ========== Header 样式 ========== */
.topology-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-icon {
  color: #409eff;
}

.header-title {
  font-size: 18px;
  font-weight: bold;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

/* ========== 图例样式 ========== */
.legend-container {
  display: flex;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #606266;
  transition: all 0.3s ease;
  padding: 4px 8px;
  border-radius: 4px;
}

.legend-item:hover {
  background: rgba(64, 158, 255, 0.1);
  transform: translateY(-1px);
}

.legend-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 2px solid #333;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
  flex-shrink: 0;
}

.root-dot {
  background: #FFD700;
  animation: pulse-gold 2s ease-in-out infinite;
}

.group-leader-dot {
  background: #4169E1;
}

.member-dot {
  background: #32CD32;
}

.byzantine-dot {
  background: #F44336;
  animation: pulse-red 2s ease-in-out infinite;
}

@keyframes pulse-gold {
  0%, 100% {
    box-shadow: 0 0 0 0 rgba(255, 215, 0, 0.7);
  }
  50% {
    box-shadow: 0 0 0 8px rgba(255, 215, 0, 0);
  }
}

@keyframes pulse-red {
  0%, 100% {
    box-shadow: 0 0 0 0 rgba(244, 67, 54, 0.7);
  }
  50% {
    box-shadow: 0 0 0 8px rgba(244, 67, 54, 0);
  }
}

.legend-label {
  font-weight: 500;
  white-space: nowrap;
}

/* ========== Canvas 容器 ========== */
.canvas-wrapper {
  position: relative;
  display: flex;
  justify-content: center;
  align-items: center;
  background: #f9f9f9;
  border-radius: 8px;
  padding: 20px;
  min-height: 740px;
}

canvas {
  border: 2px solid #e0e0e0;
  background: white;
  box-shadow: 0 4px 16px 0 rgba(0, 0, 0, 0.08);
  border-radius: 4px;
  transition: box-shadow 0.3s ease;
}

canvas:hover {
  box-shadow: 0 6px 24px 0 rgba(0, 0, 0, 0.12);
}

/* ========== 共识结果覆盖层 ========== */
.result-overlay {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  z-index: 100;
  background: rgba(255, 255, 255, 0.98);
  backdrop-filter: blur(10px);
  border-radius: 16px;
  padding: 40px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
  border: 2px solid #67c23a;
  min-width: 400px;
  text-align: center;
}

.consensus-result {
  margin: 0;
}

.result-icon {
  color: #67c23a;
  animation: scale-in 0.5s ease-out;
}

@keyframes scale-in {
  0% {
    transform: scale(0);
    opacity: 0;
  }
  50% {
    transform: scale(1.1);
  }
  100% {
    transform: scale(1);
    opacity: 1;
  }
}

/* Element Plus Result 组件样式覆盖 */
.consensus-result :deep(.el-result__title) {
  font-size: 24px;
  font-weight: bold;
  color: #303133;
  margin-top: 16px;
}

.consensus-result :deep(.el-result__subtitle) {
  font-size: 16px;
  color: #606266;
  margin-top: 8px;
}

.consensus-result :deep(.el-result__extra) {
  margin-top: 24px;
}

/* ========== 响应式设计 ========== */
@media (max-width: 900px) {
  .topology-header {
    flex-direction: column;
    align-items: flex-start;
  }
  
  .legend-container {
    width: 100%;
    justify-content: flex-start;
  }
  
  .canvas-wrapper {
    overflow-x: auto;
  }
  
  .result-overlay {
    min-width: 320px;
    padding: 24px;
  }
}

@media (max-width: 500px) {
  .header-title {
    font-size: 16px;
  }
  
  .legend-item {
    font-size: 12px;
  }
  
  .legend-dot {
    width: 10px;
    height: 10px;
  }
}
</style>
