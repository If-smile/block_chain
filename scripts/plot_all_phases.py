import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import pandas as pd
import numpy as np
import math
import os

plt.rcParams.update({
    'font.size': 11,
    'axes.titlesize': 13,
    'axes.labelsize': 12,
    'legend.fontsize': 9,
    'figure.dpi': 150,
    'savefig.dpi': 200,
})

base = os.path.dirname(__file__)

csvs = [
    os.path.join(base, 'Experiment2_Phase2_N16_80_DR95_98_99_R1000.csv'),
    os.path.join(base, 'Experiment2_Phase3_N16_100_DR90_92_94_95_96_R1000.csv'),
]

frames = []
for c in csvs:
    if os.path.exists(c):
        tmp = pd.read_csv(c)
        if 'First-View Raw Reliability' not in tmp.columns and 'First-View Success Rate (%)' in tmp.columns:
            tmp['First-View Raw Reliability'] = tmp['First-View Success Rate (%)'].str.rstrip('%').astype(float) / 100
        frames.append(tmp)

df = pd.concat(frames, ignore_index=True)
df = df.drop_duplicates(subset=['Delivery Rate (%)', 'Node Count (N)'], keep='last')
df = df.sort_values(['Delivery Rate (%)', 'Node Count (N)'])

def compute_params(n):
    k = max(1, round(math.sqrt(n)))
    f = (n - 1) // 3
    g = n / k
    f_local = (int(g) - 1) // 3
    return k, f, g, f_local

all_n = sorted(df['Node Count (N)'].unique())
k_jumps = [all_n[i] for i in range(1, len(all_n))
           if compute_params(all_n[i])[0] != compute_params(all_n[i-1])[0]]

drs = sorted(df['Delivery Rate (%)'].unique())

# ── Color palette ──
cmap = plt.cm.RdYlGn
dr_colors = {dr: cmap((dr - 88) / 14) for dr in drs}

# ════════════════════════════════════════════════════════════
# FIGURE 1: Final Reliability — all DRs
# ════════════════════════════════════════════════════════════
fig1, ax1 = plt.subplots(figsize=(16, 7))
for dr in drs:
    sub = df[df['Delivery Rate (%)'] == dr].sort_values('Node Count (N)')
    ax1.plot(sub['Node Count (N)'], sub['Raw Reliability'] * 100,
             marker='o', markersize=3.5, linewidth=1.3,
             label=f'DR={dr}%', color=dr_colors[dr])
for kj in k_jumps:
    ax1.axvline(kj, color='red', alpha=0.2, linewidth=0.8, linestyle='--')
    k_val = compute_params(kj)[0]
    ax1.text(kj, 104, f'K={k_val}', fontsize=7, ha='center', color='red', alpha=0.6)
ax1.set_xlabel('Node Count (N)')
ax1.set_ylabel('Final Reliability (%)')
ax1.set_title('Final Reliability vs Node Count (All Delivery Rates)\nRed dashed = K transition')
ax1.legend(loc='upper right', ncol=2)
ax1.set_ylim(-5, 110)
ax1.grid(True, alpha=0.3)
plt.tight_layout()
fig1.savefig(os.path.join(base, 'fig_all_final_reliability.png'), bbox_inches='tight')
print("Saved: fig_all_final_reliability.png")

# ════════════════════════════════════════════════════════════
# FIGURE 2: First-View Reliability — all DRs
# ════════════════════════════════════════════════════════════
fig2, ax2 = plt.subplots(figsize=(16, 7))
for dr in drs:
    sub = df[df['Delivery Rate (%)'] == dr].sort_values('Node Count (N)')
    ax2.plot(sub['Node Count (N)'], sub['First-View Raw Reliability'] * 100,
             marker='s', markersize=3, linewidth=1.2,
             label=f'DR={dr}%', color=dr_colors[dr])
for kj in k_jumps:
    ax2.axvline(kj, color='red', alpha=0.2, linewidth=0.8, linestyle='--')
ax2.set_xlabel('Node Count (N)')
ax2.set_ylabel('First-View Reliability (%)')
ax2.set_title('First-View Reliability vs Node Count (All Delivery Rates)')
ax2.legend(loc='upper right', ncol=2)
ax2.set_ylim(-5, 110)
ax2.grid(True, alpha=0.3)
plt.tight_layout()
fig2.savefig(os.path.join(base, 'fig_all_firstview_reliability.png'), bbox_inches='tight')
print("Saved: fig_all_firstview_reliability.png")

# ════════════════════════════════════════════════════════════
# FIGURE 3: DR=90% detail with K/f jump annotations
# ════════════════════════════════════════════════════════════
fig3, ax3 = plt.subplots(figsize=(16, 6))
sub90 = df[df['Delivery Rate (%)'] == 90].sort_values('Node Count (N)')
if not sub90.empty:
    ns = sub90['Node Count (N)'].values
    ax3.plot(ns, sub90['Raw Reliability'].values * 100,
             marker='o', markersize=5, linewidth=1.8, color='#2196F3',
             label='Final Reliability (DR=90%)', zorder=5)
    ax3.plot(ns, sub90['First-View Raw Reliability'].values * 100,
             marker='s', markersize=4, linewidth=1.2, color='#FF9800',
             alpha=0.7, label='First-View Reliability (DR=90%)', zorder=4)
    for i, n in enumerate(ns):
        k, f, g, fl = compute_params(n)
        if i == 0 or compute_params(ns[i-1])[0] != k:
            ax3.axvline(n, color='red', alpha=0.4, linewidth=1, linestyle='--')
            ax3.text(n, 105, f'K={k}', fontsize=8, ha='center', color='red', fontweight='bold')
        if i > 0 and compute_params(ns[i-1])[1] != f:
            ax3.axvline(n, color='green', alpha=0.25, linewidth=0.8, linestyle=':')
    ax3.set_xlabel('Node Count (N)')
    ax3.set_ylabel('Reliability (%)')
    ax3.set_title('Reliability Oscillation at DR=90%\nRed dashed = K jump | Green dotted = f jump')
    ax3.legend(loc='upper right')
    ax3.set_ylim(-5, 115)
    ax3.grid(True, alpha=0.3)
    plt.tight_layout()
    fig3.savefig(os.path.join(base, 'fig_DR90_detail.png'), bbox_inches='tight')
    print("Saved: fig_DR90_detail.png")

# ════════════════════════════════════════════════════════════
# FIGURE 4: Final vs First-View gap for DR=95%
# ════════════════════════════════════════════════════════════
fig4, ax4 = plt.subplots(figsize=(16, 6))
sub95 = df[df['Delivery Rate (%)'] == 95].sort_values('Node Count (N)')
if not sub95.empty:
    ns = sub95['Node Count (N)'].values
    final = sub95['Raw Reliability'].values * 100
    fv = sub95['First-View Raw Reliability'].values * 100
    ax4.fill_between(ns, fv, final, alpha=0.25, color='#4CAF50',
                     label='View-Change Recovery Gap')
    ax4.plot(ns, final, marker='o', markersize=5, linewidth=1.8,
             color='#2196F3', label='Final Reliability')
    ax4.plot(ns, fv, marker='s', markersize=4, linewidth=1.2,
             color='#FF9800', label='First-View Reliability')
    for kj in k_jumps:
        if kj >= ns.min() and kj <= ns.max():
            ax4.axvline(kj, color='red', alpha=0.3, linewidth=0.8, linestyle='--')
    ax4.set_xlabel('Node Count (N)')
    ax4.set_ylabel('Reliability (%)')
    ax4.set_title('Final vs First-View Reliability at DR=95%\nGreen area = consensus recovered via View Change')
    ax4.legend(loc='lower left')
    ax4.set_ylim(-5, 110)
    ax4.grid(True, alpha=0.3)
    plt.tight_layout()
    fig4.savefig(os.path.join(base, 'fig_DR95_final_vs_firstview.png'), bbox_inches='tight')
    print("Saved: fig_DR95_final_vs_firstview.png")

# ════════════════════════════════════════════════════════════
# FIGURE 5: Discrete parameter overlay (K, f, g, q_local)
# ════════════════════════════════════════════════════════════
param_df = pd.DataFrame([
    {'N': n, 'K': compute_params(n)[0], 'f': compute_params(n)[1],
     'g': compute_params(n)[2], 'f_local': compute_params(n)[3],
     'q_global': 2 * compute_params(n)[1] + 1,
     'q_local': 2 * compute_params(n)[3] + 1}
    for n in range(16, 101)
])

fig5, (ax5a, ax5b) = plt.subplots(1, 2, figsize=(16, 5))

ax5a.step(param_df['N'], param_df['K'], where='mid', label='K = round(√N)',
          color='blue', linewidth=1.5)
ax5a_r = ax5a.twinx()
ax5a_r.step(param_df['N'], param_df['f'], where='mid', label='f = (N-1)//3',
            color='orange', linewidth=1.5, linestyle='--')
ax5a_r.step(param_df['N'], param_df['q_global'], where='mid', label='q_global = 2f+1',
            color='green', linewidth=1.2, linestyle=':')
ax5a.set_xlabel('Node Count (N)')
ax5a.set_ylabel('K', color='blue')
ax5a_r.set_ylabel('f / q_global', color='orange')
ax5a.set_title('(a) K, f, q_global vs N')
lines1, labels1 = ax5a.get_legend_handles_labels()
lines2, labels2 = ax5a_r.get_legend_handles_labels()
ax5a.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=8)
ax5a.grid(True, alpha=0.3)

ax5b.step(param_df['N'], param_df['g'], where='mid', label='Avg group size (N/K)',
          color='purple', linewidth=1.5)
ax5b_r = ax5b.twinx()
ax5b_r.step(param_df['N'], param_df['q_local'], where='mid', label='q_local = 2·f_local+1',
            color='brown', linewidth=1.5, linestyle='--')
ax5b.set_xlabel('Node Count (N)')
ax5b.set_ylabel('Group Size', color='purple')
ax5b_r.set_ylabel('Local Quorum', color='brown')
ax5b.set_title('(b) Group Size & Local Quorum vs N')
lines1, labels1 = ax5b.get_legend_handles_labels()
lines2, labels2 = ax5b_r.get_legend_handles_labels()
ax5b.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=8)
ax5b.grid(True, alpha=0.3)

plt.tight_layout()
fig5.savefig(os.path.join(base, 'fig_parameter_jumps.png'), bbox_inches='tight')
print("Saved: fig_parameter_jumps.png")

# ════════════════════════════════════════════════════════════
# FIGURE 6: Heatmap — DR vs N
# ════════════════════════════════════════════════════════════
pivot = df.pivot_table(index='Delivery Rate (%)', columns='Node Count (N)',
                       values='Raw Reliability', aggfunc='mean')
pivot = pivot.sort_index(ascending=False)

fig6, ax6 = plt.subplots(figsize=(18, 5))
im = ax6.imshow(pivot.values * 100, aspect='auto', cmap='RdYlGn',
                vmin=0, vmax=100,
                extent=[pivot.columns.min()-1, pivot.columns.max()+1,
                        pivot.index.min()-0.5, pivot.index.max()+0.5])
ax6.set_xlabel('Node Count (N)')
ax6.set_ylabel('Delivery Rate (%)')
ax6.set_title('Final Reliability Heatmap (%) — Delivery Rate vs Node Count')
cbar = plt.colorbar(im, ax=ax6, shrink=0.8)
cbar.set_label('Reliability (%)')
plt.tight_layout()
fig6.savefig(os.path.join(base, 'fig_heatmap_reliability.png'), bbox_inches='tight')
print("Saved: fig_heatmap_reliability.png")

print("\nDone! All figures saved.")
