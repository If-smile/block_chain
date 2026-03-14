import requests
import pandas as pd
import math
import time
import sys
import socketio

# 接口地址配置
API_URL = "http://127.0.0.1:8000/api/simulate"
SOCKET_URL = "http://127.0.0.1:8000"

# 实验参数设置
ROUNDS = 1000
DELIVERY_RATES = [95, 85]  # 测试正相关与负相关两种网络环境
node_configs = [9, 16, 20, 25, 36]

results = []

# 1. 初始化 Socket.IO 客户端用于接收进度
sio = socketio.Client()

@sio.on('simulation_progress')
def on_progress(data):
    progress = data.get('progress', 0)
    round_num = data.get('current_round', 0)
    rate = data.get('success_rate', 0.0)
    
    # 绘制终端进度条 (长度 40)
    bar_length = 40
    filled_len = int(bar_length * progress // 100)
    bar = '█' * filled_len + '-' * (bar_length - filled_len)
    
    # 使用 \r 实现在同一行刷新输出，不换行
    sys.stdout.write(f'\r      [{bar}] {progress}% | 轮次: {round_num}/{ROUNDS} | 实时成功率: {rate:.2f}%   ')
    sys.stdout.flush()

def run_experiment():
    print("🚀 开始执行实验二：规模悖论自动化测试 (带实时进度条)...\n")
    start_total_time = time.time()
    
    # 尝试连接到后端的 WebSocket 服务
    try:
        sio.connect(SOCKET_URL)
        print("📡 已成功连接到后端 WebSocket，实时进度监听开启。")
    except Exception as e:
        print(f"⚠️ 无法连接到 WebSocket ({e})，不影响测试，但不会显示进度条。")

    for dr in DELIVERY_RATES:
        print(f"\n========================================================")
        print(f"🌐 当前测试网络环境: Delivery Rate = {dr}%")
        print(f"========================================================")
        
        for n in node_configs:
            k = max(1, round(math.sqrt(n)))
            f = (n - 1) // 3
            
            print(f"\n▶ 正在运行: {n} 节点, {k} 分组, 容错 {f} 节点...")
            
            payload = {
                "config": {
                    "nodeCount": n,
                    "faultyNodes": f,
                    "robotNodes": n,  # [核心修复]：强制所有节点存活，消除死节点干扰
                    "topology": "full", 
                    "branchCount": k,
                    "messageDeliveryRate": dr,
                    "proposalValue": 0,
                    "maliciousProposer": False,
                    "allowTampering": False
                },
                "rounds": ROUNDS
            }
            
            try:
                start_req_time = time.time()
                
                # 发送 HTTP 仿真请求（超时放宽至 1500 秒以应对低送达率场景）
                # requests 是阻塞的，但 sio 运行在后台线程，进度条会正常刷新
                response = requests.post(API_URL, json=payload, timeout=1500)
                response.raise_for_status()
                data = response.json()
                req_time = time.time() - start_req_time
                
                rel_pct = data['reliability'] * 100
                
                # 请求完成后，强制打印 100% 进度条并换行收尾
                sys.stdout.write(f'\r      [{"█" * 40}] 100% | 轮次: {ROUNDS}/{ROUNDS} | 最终成功率: {rel_pct:.2f}%     \n')
                sys.stdout.flush()
                print(f"   ✅ 完成! 最终成功率: {rel_pct:.2f}% (本组耗时 {req_time:.2f}s)")
                
                results.append({
                    "Delivery Rate (%)": dr,
                    "Node Count (N)": n,
                    "Branch Count (K)": k,
                    "Faulty Nodes (f)": f,
                    "Total Rounds": data['rounds'],
                    "Success Rate (%)": f"{rel_pct:.2f}%",
                    "Raw Reliability": data['reliability'],
                    "Avg Latency (ms)": round(data['average_latency'] * 1000, 2)
                })
                
            except Exception as e:
                print(f"\n   ❌ 失败: {e}")

    # 实验结束，断开长连接
    if sio.connected:
        sio.disconnect()

    # 导出数据到 CSV
    df = pd.DataFrame(results)
    output_file = "Experiment2_Scaling_Results.csv"
    df.to_csv(output_file, index=False, encoding='utf-8-sig')

    end_total_time = time.time()
    print(f"\n🎉 全部实验完成！总耗时: {end_total_time - start_total_time:.2f} 秒")
    print(f"📊 数据已成功导出至当前目录的: {output_file}")

if __name__ == "__main__":
    run_experiment()