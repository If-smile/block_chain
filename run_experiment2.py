import requests
import pandas as pd
import math
import time

# 配置仿真后端的接口地址
API_URL = "http://127.0.0.1:8000/api/simulate"

# 实验参数设置
ROUNDS = 1000
DELIVERY_RATES = [95, 85] # 测试 95% (正相关) 和 85% (负相关)

# 根据你的要求：配置节点数，并自动计算最优分组 (K ≈ sqrt(N))
node_configs = [9, 16, 20, 25, 36]

results = []

print("🚀 开始执行实验二：规模悖论自动化测试...")
start_total_time = time.time()

for dr in DELIVERY_RATES:
    print(f"\n======================================")
    print(f"📡 当前测试网络环境: Delivery Rate = {dr}%")
    print(f"======================================")
    
    for n in node_configs:
        # 最低通信复杂度分组 K ≈ sqrt(N)
        k = max(1, round(math.sqrt(n)))
        # 拜占庭节点数 f = (N-1)//3
        f = (n - 1) // 3
        
        print(f"⏳ 正在运行: {n} 节点, {k} 分组, 容错 {f} 节点... ", end="", flush=True)
        
        payload = {
            "config": {
                "nodeCount": n,
                "faultyNodes": f,
                "topology": "full", # 底层实际会按双层处理
                "branchCount": k,
                "messageDeliveryRate": dr,
                "proposalValue": 0,
                "maliciousProposer": False,
                "allowTampering": False
            },
            "rounds": ROUNDS
        }
        
        try:
            # 发送请求到后端
            start_req_time = time.time()
            response = requests.post(API_URL, json=payload, timeout=1500) # 设置较长超时以防万一
            response.raise_for_status()
            data = response.json()
            req_time = time.time() - start_req_time
            
            # 记录结果
            rel_pct = data['reliability'] * 100
            print(f"完成! 成功率: {rel_pct:.2f}% (耗时 {req_time:.2f}s)")
            
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
            print(f"❌ 失败: {e}")

# 导出为 CSV 文件（Excel可直接打开）
df = pd.DataFrame(results)
output_file = "Experiment2_Scaling_Results.csv"
df.to_csv(output_file, index=False, encoding='utf-8-sig')

end_total_time = time.time()
print(f"\n✅ 全部实验完成！总耗时: {end_total_time - start_total_time:.2f} 秒")
print(f"📊 数据已成功导出至当前目录的: {output_file}")