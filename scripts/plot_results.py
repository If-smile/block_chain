import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import math
import re
import os

plt.rcParams.update({
    'font.size': 11,
    'axes.titlesize': 13,
    'axes.labelsize': 12,
    'legend.fontsize': 9,
    'figure.dpi': 150,
    'savefig.dpi': 200,
    'figure.figsize': (14, 10),
})

# ────────────────────────────────────────────────────────────
# 1. Parse the log-style results (DR=90% and DR=92% partial)
# ────────────────────────────────────────────────────────────
def parse_log_file(path):
    rows = []
    current_dr = None
    with open(path, encoding='utf-8') as f:
        for line in f:
            m_dr = re.search(r'Delivery Rate\s*=\s*(\d+)%', line)
            if m_dr:
                current_dr = int(m_dr.group(1))
                continue
            m = re.search(
                r'Final=(\d+\.\d+)%.*?First-View=(\d+\.\d+)%',
                line,
            )
            if m and current_dr is not None:
                final = float(m.group(1))
                fv = float(m.group(2))
                m_n = re.search(r'(\d+)\s+Nodes,\s*(\d+)\s+Groups.*?(\d+)\s+Nodes', prev_running)
                if m_n:
                    n = int(m_n.group(1))
                    k = int(m_n.group(2))
                    ft = int(m_n.group(3))
                    rows.append({
                        'Delivery Rate (%)': current_dr,
                        'Node Count (N)': n,
                        'Branch Count (K)': k,
                        'Faulty Nodes (f)': ft,
                        'Raw Reliability': final / 100,
                        'First-View Raw Reliability': fv / 100,
                    })
            if '▶ Running:' in line:
                prev_running = line
    return pd.DataFrame(rows)


log_path = os.path.join(
    os.path.expanduser('~'),
    r"OneDrive - University of Glasgow\four\fyp\新建 文本文档.txt",
)
df_log = parse_log_file(log_path) if os.path.exists(log_path) else pd.DataFrame()

# ────────────────────────────────────────────────────────────
# 2. Load CSV results
# ────────────────────────────────────────────────────────────
csv_phase2 = os.path.join(os.path.dirname(__file__), 'Experiment2_Phase2_N16_80_DR95_98_99_R1000.csv')
df_csv = pd.read_csv(csv_phase2) if os.path.exists(csv_phase2) else pd.DataFrame()

if not df_csv.empty and 'First-View Raw Reliability' not in df_csv.columns:
    if 'First-View Success Rate (%)' in df_csv.columns:
        df_csv['First-View Raw Reliability'] = df_csv['First-View Success Rate (%)'].str.rstrip('%').astype(float) / 100

# ────────────────────────────────────────────────────────────
# 3. Merge all data
# ────────────────────────────────────────────────────────────
cols = ['Delivery Rate (%)', 'Node Count (N)', 'Branch Count (K)',
        'Faulty Nodes (f)', 'Raw Reliability', 'First-View Raw Reliability']

frames = []
if not df_log.empty:
    frames.append(df_log[cols])
if not df_csv.empty:
    frames.append(df_csv[cols])

if not frames:
    print("No data found!")
    exit(1)

df = pd.concat(frames, ignore_index=True)
df = df.drop_duplicates(subset=['Delivery Rate (%)', 'Node Count (N)'], keep='last')
df = df.sort_values(['Delivery Rate (%)', 'Node Count (N)'])

# ────────────────────────────────────────────────────────────
# 4. Compute discrete parameter jumps for annotation
# ────────────────────────────────────────────────────────────
def compute_params(n):
    k = max(1, round(math.sqrt(n)))
    f = (n - 1) // 3
    g = n / k
    f_local = (int(g) - 1) // 3
    q_global = 2 * f + 1
    q_local = 2 * f_local + 1
    return k, f, g, f_local, q_global, q_local

all_n = sorted(df['Node Count (N)'].unique())
param_df = pd.DataFrame([
    {'N': n, 'K': compute_params(n)[0], 'f': compute_params(n)[1],
     'g': compute_params(n)[2], 'f_local': compute_params(n)[3],
     'q_global': compute_params(n)[4], 'q_local': compute_params(n)[5]}
    for n in all_n
])

k_jumps = [all_n[i] for i in range(1, len(all_n))
           if compute_params(all_n[i])[0] != compute_params(all_n[i-1])[0]]

# ────────────────────────────────────────────────────────────
# 5. FIGURE 1: Final Reliability vs N (multi-DR, with K-jump markers)
# ────────────────────────────────────────────────────────────
fig, axes = plt.subplots(2, 2, figsize=(16, 12))

# --- Panel (a): Final reliability ---
ax = axes[0, 0]
drs = sorted(df['Delivery Rate (%)'].unique())
colors = plt.cm.viridis(np.linspace(0.15, 0.85, len(drs)))
for dr, c in zip(drs, colors):
    sub = df[df['Delivery Rate (%)'] == dr].sort_values('Node Count (N)')
    ax.plot(sub['Node Count (N)'], sub['Raw Reliability'] * 100,
            marker='o', markersize=3, linewidth=1.2, label=f'DR={dr}%', color=c)
for kj in k_jumps:
    ax.axvline(kj, color='red', alpha=0.25, linewidth=0.8, linestyle='--')
ax.set_xlabel('Node Count (N)')
ax.set_ylabel('Final Reliability (%)')
ax.set_title('(a) Final Reliability vs Node Count')
ax.legend(loc='upper right', ncol=2)
ax.set_ylim(-5, 105)
ax.grid(True, alpha=0.3)
for kj in k_jumps:
    k_val = compute_params(kj)[0]
    ax.text(kj, 103, f'K={k_val}', fontsize=7, ha='center', color='red', alpha=0.7)

# --- Panel (b): First-View reliability ---
ax = axes[0, 1]
for dr, c in zip(drs, colors):
    sub = df[df['Delivery Rate (%)'] == dr].sort_values('Node Count (N)')
    if 'First-View Raw Reliability' in sub.columns:
        ax.plot(sub['Node Count (N)'], sub['First-View Raw Reliability'] * 100,
                marker='s', markersize=3, linewidth=1.2, label=f'DR={dr}%', color=c)
for kj in k_jumps:
    ax.axvline(kj, color='red', alpha=0.25, linewidth=0.8, linestyle='--')
ax.set_xlabel('Node Count (N)')
ax.set_ylabel('First-View Reliability (%)')
ax.set_title('(b) First-View Reliability vs Node Count')
ax.legend(loc='upper right', ncol=2)
ax.set_ylim(-5, 105)
ax.grid(True, alpha=0.3)

# --- Panel (c): K, f, q_global step functions ---
ax = axes[1, 0]
ax.step(param_df['N'], param_df['K'], where='mid', label='K = round(sqrt(N))',
        color='blue', linewidth=1.5)
ax2 = ax.twinx()
ax2.step(param_df['N'], param_df['f'], where='mid', label='f = (N-1)//3',
         color='orange', linewidth=1.5, linestyle='--')
ax2.step(param_df['N'], param_df['q_global'], where='mid', label='q_global = 2f+1',
         color='green', linewidth=1.2, linestyle=':')
ax.set_xlabel('Node Count (N)')
ax.set_ylabel('K (Branch Count)', color='blue')
ax2.set_ylabel('f / q_global', color='orange')
ax.set_title('(c) Discrete Parameter Jumps vs N')
lines1, labels1 = ax.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=8)
ax.grid(True, alpha=0.3)

# --- Panel (d): Group size and local quorum ---
ax = axes[1, 1]
ax.step(param_df['N'], param_df['g'], where='mid', label='Avg group size (N/K)',
        color='purple', linewidth=1.5)
ax3 = ax.twinx()
ax3.step(param_df['N'], param_df['q_local'], where='mid', label='q_local = 2*f_local+1',
         color='brown', linewidth=1.5, linestyle='--')
ax.set_xlabel('Node Count (N)')
ax.set_ylabel('Avg Group Size', color='purple')
ax3.set_ylabel('Local Quorum (q_local)', color='brown')
ax.set_title('(d) Group Size & Local Quorum vs N')
lines1, labels1 = ax.get_legend_handles_labels()
lines2, labels2 = ax3.get_legend_handles_labels()
ax.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=8)
ax.grid(True, alpha=0.3)

plt.suptitle('Double-Layer HotStuff: Reliability Oscillation Analysis\n'
             '(Red dashed lines = K transition points)',
             fontsize=14, fontweight='bold', y=1.01)
plt.tight_layout()
plt.savefig('fig1_reliability_oscillation.png', bbox_inches='tight')
print("Saved: fig1_reliability_oscillation.png")

# ────────────────────────────────────────────────────────────
# 6. FIGURE 2: Overlay — reliability + K/f on same axis (DR=90 focus)
# ────────────────────────────────────────────────────────────
fig2, ax_main = plt.subplots(figsize=(14, 6))

focus_dr = 90
sub90 = df[df['Delivery Rate (%)'] == focus_dr].sort_values('Node Count (N)')

if not sub90.empty:
    ax_main.plot(sub90['Node Count (N)'], sub90['Raw Reliability'] * 100,
                 marker='o', markersize=5, linewidth=1.8, color='#2196F3',
                 label=f'Final Reliability (DR={focus_dr}%)', zorder=5)
    if 'First-View Raw Reliability' in sub90.columns:
        ax_main.plot(sub90['Node Count (N)'], sub90['First-View Raw Reliability'] * 100,
                     marker='s', markersize=4, linewidth=1.2, color='#FF9800',
                     alpha=0.7, label=f'First-View Reliability (DR={focus_dr}%)', zorder=4)

    ns = sub90['Node Count (N)'].values
    for i, n in enumerate(ns):
        k, f, g, f_local, q_g, q_l = compute_params(n)
        if i == 0 or compute_params(ns[i-1])[0] != k:
            ax_main.axvline(n, color='red', alpha=0.4, linewidth=1, linestyle='--')
            ax_main.text(n, 102, f'K={k}', fontsize=7, ha='center', color='red',
                         fontweight='bold')
        if i == 0 or compute_params(ns[i-1])[1] != f:
            ax_main.axvline(n, color='green', alpha=0.3, linewidth=0.8, linestyle=':')

    ax_main.set_xlabel('Node Count (N)')
    ax_main.set_ylabel('Reliability (%)')
    ax_main.set_title(f'Reliability Oscillation at DR={focus_dr}%\n'
                      f'Red dashed = K jump | Green dotted = f jump')
    ax_main.legend(loc='upper right')
    ax_main.set_ylim(-5, 110)
    ax_main.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig('fig2_DR90_oscillation_detail.png', bbox_inches='tight')
    print("Saved: fig2_DR90_oscillation_detail.png")
else:
    print(f"No data for DR={focus_dr}%, skipping fig2")

# ────────────────────────────────────────────────────────────
# 7. FIGURE 3: Final vs First-View gap (DR=95)
# ────────────────────────────────────────────────────────────
fig3, ax3 = plt.subplots(figsize=(14, 6))

focus_dr2 = 95
sub95 = df[df['Delivery Rate (%)'] == focus_dr2].sort_values('Node Count (N)')

if not sub95.empty and 'First-View Raw Reliability' in sub95.columns:
    ns = sub95['Node Count (N)'].values
    final = sub95['Raw Reliability'].values * 100
    fv = sub95['First-View Raw Reliability'].values * 100

    ax3.fill_between(ns, fv, final, alpha=0.25, color='#4CAF50',
                     label='View-Change Recovery Gap')
    ax3.plot(ns, final, marker='o', markersize=5, linewidth=1.8,
             color='#2196F3', label='Final Reliability')
    ax3.plot(ns, fv, marker='s', markersize=4, linewidth=1.2,
             color='#FF9800', label='First-View Reliability')

    for n in k_jumps:
        if n >= ns.min() and n <= ns.max():
            ax3.axvline(n, color='red', alpha=0.3, linewidth=0.8, linestyle='--')

    ax3.set_xlabel('Node Count (N)')
    ax3.set_ylabel('Reliability (%)')
    ax3.set_title(f'Final vs First-View Reliability at DR={focus_dr2}%\n'
                  f'Green area = consensus recovered via View Change')
    ax3.legend(loc='lower left')
    ax3.set_ylim(-5, 110)
    ax3.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig('fig3_final_vs_firstview_DR95.png', bbox_inches='tight')
    print("Saved: fig3_final_vs_firstview_DR95.png")
else:
    print(f"No data for DR={focus_dr2}%, skipping fig3")

print("\nDone! All figures saved to current directory.")
