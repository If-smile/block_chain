import requests
import pandas as pd
import math
import time
import sys
import socketio

# API Configuration
API_URL = "http://127.0.0.1:8000/api/simulate"
SOCKET_URL = "http://127.0.0.1:8000"

# Experiment Parameters
ROUNDS = 1000
DELIVERY_RATES = [95, 85]  # Testing positive and negative correlation environments
node_configs = [9, 16, 20, 25, 36]

results = []

# 1. Initialize Socket.IO client for progress tracking
sio = socketio.Client()

@sio.on('simulation_progress')
def on_progress(data):
    progress = data.get('progress', 0)
    round_num = data.get('current_round', 0)
    rate = data.get('success_rate', 0.0)
    
    # Draw terminal progress bar (length 40)
    bar_length = 40
    filled_len = int(bar_length * progress // 100)
    bar = '█' * filled_len + '-' * (bar_length - filled_len)
    
    # Use \r to refresh on the same line without newline
    sys.stdout.write(f'\r      [{bar}] {progress}% | Round: {round_num}/{ROUNDS} | Real-time Rate: {rate:.2f}%   ')
    sys.stdout.flush()

def run_experiment():
    print("🚀 Starting Experiment 2: Scaling Paradox Automated Test (with real-time progress)...\n")
    start_total_time = time.time()
    
    # Attempt to connect to backend WebSocket
    try:
        sio.connect(SOCKET_URL)
        print("📡 Successfully connected to backend WebSocket. Real-time progress monitoring active.")
    except Exception as e:
        print(f"⚠️ Could not connect to WebSocket ({e}). Test will proceed, but progress bar will not be shown.")

    for dr in DELIVERY_RATES:
        print(f"\n========================================================")
        print(f"🌐 Current Network Environment: Delivery Rate = {dr}%")
        print(f"========================================================")
        
        for n in node_configs:
            k = max(1, round(math.sqrt(n)))
            f = (n - 1) // 3
            
            print(f"\n▶ Running: {n} Nodes, {k} Groups, Fault Tolerance: {f} Nodes...")
            
            payload = {
                "config": {
                    "nodeCount": n,
                    "faultyNodes": f,
                    "robotNodes": n,  # [Core fix]: Force all nodes to be alive, eliminating dead node interference
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
                
                # Send HTTP simulation request (timeout relaxed to 1500s for low delivery rate scenarios)
                # requests is blocking, but sio runs in a background thread, so progress bar updates normally
                response = requests.post(API_URL, json=payload, timeout=1500)
                response.raise_for_status()
                data = response.json()
                req_time = time.time() - start_req_time
                
                rel_pct = data['reliability'] * 100
                
                # Force print 100% progress bar and add newline upon completion
                sys.stdout.write(f'\r      [{"█" * 40}] 100% | Round: {ROUNDS}/{ROUNDS} | Final Rate: {rel_pct:.2f}%     \n')
                sys.stdout.flush()
                print(f"   ✅ Completed! Final Success Rate: {rel_pct:.2f}% (Time taken: {req_time:.2f}s)")
                
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
                print(f"\n   ❌ Failed: {e}")

    # Disconnect after experiment finishes
    if sio.connected:
        sio.disconnect()

    # Export data to CSV
    df = pd.DataFrame(results)
    output_file = "Experiment2_Scaling_Results.csv"
    df.to_csv(output_file, index=False, encoding='utf-8-sig')

    end_total_time = time.time()
    print(f"\n🎉 All experiments completed! Total time: {end_total_time - start_total_time:.2f} seconds")
    print(f"📊 Data successfully exported to current directory: {output_file}")

if __name__ == "__main__":
    run_experiment()