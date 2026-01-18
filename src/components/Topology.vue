<template>
  <div class="canvas-container">
    <canvas ref="canvas" width="800" height="700"></canvas>
    <div class="consensus-result" v-if="finalConsensus">
      <h3>最终共识结果</h3>
      <p>{{ finalConsensus }}</p>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted, watch } from "vue";

export default {
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
            finalConsensus.value = props.simulationResult?.consensus || "完成";
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

<style>
.canvas-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  background: #f9f9f9;
  border-radius: 8px;
  padding: 10px;
}
canvas {
  border: 1px solid #e0e0e0;
  background: white;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
}
</style>
