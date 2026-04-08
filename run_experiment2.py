import requests
import pandas as pd
import math
import time
import sys
import socketio
import argparse
import os

# API Configuration
API_URL = "http://127.0.0.1:8000/api/simulate"
SOCKET_URL = "http://127.0.0.1:8000"

# Default experiment parameters
DEFAULT_ROUNDS = 3000
DEFAULT_DELIVERY_RATES = [95, 98, 99]
DEFAULT_NODE_START = 53
DEFAULT_NODE_END = 200

# 1. Initialize Socket.IO client for progress tracking
sio = socketio.Client()
CURRENT_ROUNDS = DEFAULT_ROUNDS

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
    sys.stdout.write(f'\r      [{bar}] {progress}% | Round: {round_num}/{CURRENT_ROUNDS} | Real-time Rate: {rate:.2f}%   ')
    sys.stdout.flush()

def parse_args():
    parser = argparse.ArgumentParser(description="Run Monte Carlo scaling experiments with resume support.")
    parser.add_argument("--node-start", type=int, default=DEFAULT_NODE_START, help="Start node count (inclusive)")
    parser.add_argument("--node-end", type=int, default=DEFAULT_NODE_END, help="End node count (inclusive)")
    parser.add_argument("--step", type=int, default=1, help="Node count step")
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS, help="Simulation rounds per case")
    parser.add_argument(
        "--delivery-rates",
        nargs="+",
        type=int,
        default=DEFAULT_DELIVERY_RATES,
        help="Delivery rates to test, e.g. --delivery-rates 95 98 99",
    )
    parser.add_argument(
        "--output",
        default="Experiment2_Scaling_Results_53_200.csv",
        help="Output CSV path",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip cases already present in output CSV",
    )
    return parser.parse_args()

def load_completed_cases(output_file):
    completed = set()
    if not os.path.exists(output_file):
        return completed
    try:
        df = pd.read_csv(output_file)
        for _, row in df.iterrows():
            completed.add((int(row["Delivery Rate (%)"]), int(row["Node Count (N)"])))
    except Exception:
        pass
    return completed

def run_experiment(args):
    global CURRENT_ROUNDS
    CURRENT_ROUNDS = args.rounds

    if args.node_start > args.node_end:
        raise ValueError("--node-start cannot be greater than --node-end")
    if args.step <= 0:
        raise ValueError("--step must be > 0")

    node_configs = list(range(args.node_start, args.node_end + 1, args.step))
    completed_cases = load_completed_cases(args.output) if args.resume else set()
    results = []

    print("🚀 Starting Experiment 2: Scaling Paradox Automated Test (with real-time progress)...\n")
    print(
        f"📌 Config: nodes={args.node_start}-{args.node_end} step={args.step}, "
        f"delivery={args.delivery_rates}, rounds={args.rounds}, output={args.output}, resume={args.resume}"
    )
    start_total_time = time.time()
    
    # Attempt to connect to backend WebSocket
    try:
        sio.connect(SOCKET_URL)
        print("📡 Successfully connected to backend WebSocket. Real-time progress monitoring active.")
    except Exception as e:
        print(f"⚠️ Could not connect to WebSocket ({e}). Test will proceed, but progress bar will not be shown.")

    for dr in args.delivery_rates:
        print(f"\n========================================================")
        print(f"🌐 Current Network Environment: Delivery Rate = {dr}%")
        print(f"========================================================")
        
        for n in node_configs:
            if (dr, n) in completed_cases:
                print(f"\n⏭ Skipping completed case: DR={dr}%, N={n}")
                continue
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
                "rounds": args.rounds
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
                sys.stdout.write(f'\r      [{"█" * 40}] 100% | Round: {args.rounds}/{args.rounds} | Final Rate: {rel_pct:.2f}%     \n')
                sys.stdout.flush()
                print(f"   ✅ Completed! Final Success Rate: {rel_pct:.2f}% (Time taken: {req_time:.2f}s)")
                
                row = {
                    "Delivery Rate (%)": dr,
                    "Node Count (N)": n,
                    "Branch Count (K)": k,
                    "Faulty Nodes (f)": f,
                    "Total Rounds": data['rounds'],
                    "Success Rate (%)": f"{rel_pct:.2f}%",
                    "Raw Reliability": data['reliability'],
                    "Avg Latency (ms)": round(data['average_latency'] * 1000, 2)
                }
                results.append(row)
                completed_cases.add((dr, n))

                # Incremental persistence: save after every finished case
                pd.DataFrame(results).to_csv(
                    args.output,
                    index=False,
                    encoding='utf-8-sig',
                    mode='a' if os.path.exists(args.output) else 'w',
                    header=not os.path.exists(args.output),
                )
                results.clear()
                
            except Exception as e:
                print(f"\n   ❌ Failed: {e}")

    # Disconnect after experiment finishes
    if sio.connected:
        sio.disconnect()

    end_total_time = time.time()
    print(f"\n🎉 All experiments completed! Total time: {end_total_time - start_total_time:.2f} seconds")
    print(f"📊 Data successfully exported to current directory: {args.output}")

if __name__ == "__main__":
    run_experiment(parse_args())