"""
Final comprehensive analysis: mathematical formula + oscillation explanation.
Generates publication-quality figures.
"""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
import math
import os
from scipy.stats import binom

base = os.path.dirname(__file__)
plt.rcParams.update({
    'font.size': 12, 'axes.titlesize': 14, 'axes.labelsize': 13,
    'legend.fontsize': 10, 'figure.dpi': 150, 'savefig.dpi': 200,
    'font.family': 'serif',
})

ALPHA = 3.73  # calibrated exponent

# ── Data loading ──
csvs = [
    os.path.join(base, 'Experiment2_Phase2_N16_80_DR95_98_99_R1000.csv'),
    os.path.join(base, 'Experiment2_Phase3_N16_100_DR90_92_94_95_96_R1000.csv'),
]
frames = [pd.read_csv(c) for c in csvs if os.path.exists(c)]
df = pd.concat(frames, ignore_index=True)
df = df.drop_duplicates(subset=['Delivery Rate (%)', 'Node Count (N)'], keep='last')
df = df.sort_values(['Delivery Rate (%)', 'Node Count (N)'])

# ── Model ──

def compute_groups(N):
    K = max(1, round(math.sqrt(N)))
    base_size = N // K
    remainder = N % K
    return K, [base_size + 1 if gid < remainder else base_size for gid in range(K)]

def compute_global_params(N):
    K, groups = compute_groups(N)
    f = (N - 1) // 3
    q_global = 2 * f + 1
    return K, groups, f, q_global

def compute_local_threshold(g):
    return 2 * ((g - 1) // 3) + 1

def P_single_phase(N, p_percent, alpha=ALPHA):
    K, groups, f, q_global = compute_global_params(N)
    p_eff = (p_percent / 100.0) ** alpha

    def group_pmf(g, is_root):
        n_v = g - 1
        q_l = compute_local_threshold(g)
        pmf = {}
        for k in range(n_v + 1):
            prob = binom.pmf(k, n_v, p_eff)
            w_g = k if k >= q_l else 0
            if not is_root:
                for gl in [0, 1]:
                    gp = p_eff if gl else (1 - p_eff)
                    w = w_g + gl
                    pmf[w] = pmf.get(w, 0.0) + prob * gp
            else:
                pmf[w_g] = pmf.get(w_g, 0.0) + prob
        return pmf

    def convolve(a, b):
        r = {}
        for w1, p1 in a.items():
            for w2, p2 in b.items():
                w = w1 + w2
                r[w] = r.get(w, 0.0) + p1 * p2
        return r

    total = group_pmf(groups[0], True)
    for j in range(1, len(groups)):
        total = convolve(total, group_pmf(groups[j], False))
    return sum(p for w, p in total.items() if w >= q_global)

def P_first_view(N, p, alpha=ALPHA):
    return P_single_phase(N, p, alpha) ** 3

def P_final(N, p, alpha=ALPHA, V=14):
    return 1 - (1 - P_first_view(N, p, alpha)) ** V


# ════════════════════════════════════════════════════════════
# FIGURE 1 (Publication): Complete oscillation mechanism
# ════════════════════════════════════════════════════════════

fig1 = plt.figure(figsize=(18, 20))
gs = fig1.add_gridspec(4, 2, hspace=0.35, wspace=0.3)

ns = list(range(16, 101))

# ── Panel (a): K and group sizes ──
ax_a = fig1.add_subplot(gs[0, 0])
ks = [compute_groups(n)[0] for n in ns]
min_gs = [min(compute_groups(n)[1]) for n in ns]
max_gs = [max(compute_groups(n)[1]) for n in ns]

ax_a.fill_between(ns, min_gs, max_gs, alpha=0.2, color='blue')
ax_a.step(ns, min_gs, where='mid', color='blue', linewidth=1.5, label='Min group size')
ax_a.step(ns, max_gs, where='mid', color='blue', linewidth=1.5, linestyle='--', label='Max group size')
ax_a2 = ax_a.twinx()
ax_a2.step(ns, ks, where='mid', color='red', linewidth=2, label='K = round(√N)')
ax_a.set_ylabel('Group Size (g)', color='blue')
ax_a2.set_ylabel('Branch Count (K)', color='red')
ax_a.set_title('(a) Group Structure')
lines1, labels1 = ax_a.get_legend_handles_labels()
lines2, labels2 = ax_a2.get_legend_handles_labels()
ax_a.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=8)
ax_a.grid(True, alpha=0.2)

# ── Panel (b): Quorum thresholds ──
ax_b = fig1.add_subplot(gs[0, 1])
q_globals = [2 * ((n - 1) // 3) + 1 for n in ns]
q_locals_min = [compute_local_threshold(min(compute_groups(n)[1])) for n in ns]
q_locals_max = [compute_local_threshold(max(compute_groups(n)[1])) for n in ns]

ax_b.step(ns, q_globals, where='mid', color='green', linewidth=2, label='q_global = 2f+1')
ax_b2 = ax_b.twinx()
ax_b2.step(ns, q_locals_min, where='mid', color='purple', linewidth=1.5, label='q_local (min g)')
ax_b2.step(ns, q_locals_max, where='mid', color='purple', linewidth=1.5, linestyle='--', label='q_local (max g)')
ax_b.set_ylabel('Global Quorum', color='green')
ax_b2.set_ylabel('Local Quorum', color='purple')
ax_b.set_title('(b) Quorum Thresholds')
lines1, labels1 = ax_b.get_legend_handles_labels()
lines2, labels2 = ax_b2.get_legend_handles_labels()
ax_b.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=8)
ax_b.grid(True, alpha=0.2)

# ── Panel (c): Quorum difficulty ratio ──
ax_c = fig1.add_subplot(gs[1, 0])
for n in ns:
    min_g = min(compute_groups(n)[1])
    q_l = compute_local_threshold(min_g)
    ratio = q_l / max(min_g - 1, 1)
    color = '#F44336' if ratio >= 1.0 else ('#FF9800' if ratio > 0.8 else '#4CAF50')
    ax_c.bar(n, ratio, width=1.8, color=color, alpha=0.75, edgecolor='none')

ax_c.axhline(2/3, color='blue', linewidth=1, linestyle='--', alpha=0.5, label='BFT bound (2/3)')
ax_c.axhline(1.0, color='red', linewidth=1, linestyle=':', alpha=0.5, label='ratio = 1 (impossible)')
ax_c.set_ylabel('q_local / (g-1)')
ax_c.set_title('(c) Quorum Difficulty Ratio')
ax_c.legend(fontsize=8)
ax_c.set_ylim(0.5, 1.15)
ax_c.grid(True, alpha=0.2)

# ── Panel (d): Local quorum pass probability ──
ax_d = fig1.add_subplot(gs[1, 1])
for dr, color, ls in [(90, '#F44336', '-'), (94, '#FF9800', '-'), (95, '#4CAF50', '-'), (98, '#2196F3', '--')]:
    p_eff = (dr / 100.0) ** ALPHA
    weakest = []
    for n in ns:
        K, groups, f, q_global = compute_global_params(n)
        probs = []
        for g in groups:
            q_l = compute_local_threshold(g)
            nv = g - 1
            probs.append(1 - binom.cdf(q_l - 1, nv, p_eff) if nv >= q_l else 0.0)
        weakest.append(min(probs))
    ax_d.plot(ns, [w * 100 for w in weakest], color=color, linewidth=1.5,
              linestyle=ls, label=f'DR={dr}%')

ax_d.set_ylabel('P(weakest group passes) (%)')
ax_d.set_title(f'(d) Weakest Group Local Quorum Probability (α={ALPHA:.2f})')
ax_d.legend(fontsize=8)
ax_d.grid(True, alpha=0.2)
ax_d.set_ylim(-5, 105)

# ── Panel (e): Theory vs Experiment — First-View ──
ax_e = fig1.add_subplot(gs[2, :])
for dr, color, marker in [(90, '#F44336', 'o'), (92, '#FF5722', 's'),
                            (94, '#FF9800', '^'), (95, '#4CAF50', 'D'),
                            (96, '#8BC34A', 'v'), (98, '#2196F3', '<'),
                            (99, '#3F51B5', '>')]:
    sub = df[df['Delivery Rate (%)'] == dr].sort_values('Node Count (N)')
    if sub.empty:
        continue
    ns_exp = sub['Node Count (N)'].values
    fv_exp = sub['First-View Raw Reliability'].values * 100
    fv_theory = [P_first_view(n, dr) * 100 for n in ns_exp]
    ax_e.plot(ns_exp, fv_exp, marker=marker, markersize=4, linewidth=1.2,
              color=color, label=f'Exp DR={dr}%')
    ax_e.plot(ns_exp, fv_theory, '--', linewidth=0.8, color=color, alpha=0.5)

ax_e.set_xlabel('Node Count (N)')
ax_e.set_ylabel('First-View Reliability (%)')
ax_e.set_title(f'(e) First-View: Experiment (solid) vs Theory (dashed), α={ALPHA:.2f}')
ax_e.legend(fontsize=7, ncol=4, loc='upper right')
ax_e.grid(True, alpha=0.2)
ax_e.set_ylim(-5, 110)

# ── Panel (f): Theory vs Experiment — Final ──
ax_f = fig1.add_subplot(gs[3, :])
for dr, color, marker in [(90, '#F44336', 'o'), (92, '#FF5722', 's'),
                            (94, '#FF9800', '^'), (95, '#4CAF50', 'D'),
                            (96, '#8BC34A', 'v'), (98, '#2196F3', '<'),
                            (99, '#3F51B5', '>')]:
    sub = df[df['Delivery Rate (%)'] == dr].sort_values('Node Count (N)')
    if sub.empty:
        continue
    ns_exp = sub['Node Count (N)'].values
    final_exp = sub['Raw Reliability'].values * 100
    final_theory = [P_final(n, dr) * 100 for n in ns_exp]
    ax_f.plot(ns_exp, final_exp, marker=marker, markersize=4, linewidth=1.2,
              color=color, label=f'Exp DR={dr}%')
    ax_f.plot(ns_exp, final_theory, '--', linewidth=0.8, color=color, alpha=0.5)

ax_f.set_xlabel('Node Count (N)')
ax_f.set_ylabel('Final Reliability (%)')
ax_f.set_title(f'(f) Final: Experiment (solid) vs Theory (dashed), α={ALPHA:.2f}, V=14')
ax_f.legend(fontsize=7, ncol=4, loc='lower right')
ax_f.grid(True, alpha=0.2)
ax_f.set_ylim(-5, 110)

fig1.savefig(os.path.join(base, 'fig_FINAL_comprehensive.png'), bbox_inches='tight')
print("Saved: fig_FINAL_comprehensive.png")

# ════════════════════════════════════════════════════════════
# FIGURE 2 (Publication): Why N=16,22,34,44,70,80,82 are "bad"
# ════════════════════════════════════════════════════════════

fig2, (ax2a, ax2b) = plt.subplots(2, 1, figsize=(18, 10))

# Show reliability at DR=95% with annotations
sub95 = df[df['Delivery Rate (%)'] == 95].sort_values('Node Count (N)')
ns95 = sub95['Node Count (N)'].values
rel95 = sub95['Raw Reliability'].values * 100

ax2a.plot(ns95, rel95, 'o-', color='#2196F3', linewidth=2, markersize=6, zorder=5)

# Annotate specific "bad" points
bad_ns = [16, 22, 34, 38, 44, 70, 72, 80, 82]
for n in bad_ns:
    if n in ns95:
        idx = list(ns95).index(n)
        r = rel95[idx]
        K, groups, f, q_global = compute_global_params(n)
        min_g = min(groups)
        q_l = compute_local_threshold(min_g)
        ratio = q_l / max(min_g - 1, 1)
        ax2a.annotate(
            f'N={n}\nK={K}, g_min={min_g}\nq_l/g={ratio:.2f}',
            xy=(n, r), xytext=(n, r - 18),
            fontsize=7, ha='center',
            arrowprops=dict(arrowstyle='->', color='red', lw=0.8),
            bbox=dict(boxstyle='round,pad=0.3', facecolor='lightyellow', alpha=0.8),
        )

# Highlight K transitions
for i in range(1, len(ns)):
    if compute_groups(ns[i])[0] != compute_groups(ns[i]-1)[0]:
        ax2a.axvspan(ns[i]-0.5, ns[i]+0.5, color='red', alpha=0.15)

ax2a.set_ylabel('Final Reliability (%)')
ax2a.set_title('Why Certain Node Counts Have Low Reliability (DR=95%)')
ax2a.grid(True, alpha=0.2)
ax2a.set_ylim(50, 105)

# Panel B: Concrete examples table
examples = [
    (24, 95), (25, 95),  # smooth growth
    (31, 95), (32, 95),  # K jump
    (54, 95), (70, 95),  # peak vs valley
    (78, 95), (80, 95),  # another drop
    (88, 95), (90, 95),  # recovery
]
table_data = []
for N, dr in examples:
    K, groups, f, q_global = compute_global_params(N)
    min_g = min(groups)
    max_g = max(groups)
    q_l = compute_local_threshold(min_g)
    p_eff = (dr / 100.0) ** ALPHA
    p_local = 1 - binom.cdf(q_l - 1, min_g - 1, p_eff) if (min_g - 1) >= q_l else 0
    p_ph = P_single_phase(N, dr)
    p_fv = P_first_view(N, dr)

    sub = df[(df['Delivery Rate (%)'] == dr) & (df['Node Count (N)'] == N)]
    exp_fv = sub['First-View Raw Reliability'].values[0] * 100 if not sub.empty else float('nan')
    exp_final = sub['Raw Reliability'].values[0] * 100 if not sub.empty else float('nan')

    table_data.append([
        f'{N}', f'{K}', f'{min_g}-{max_g}', f'{q_l}',
        f'{q_l/(min_g-1):.2f}', f'{p_local*100:.1f}%',
        f'{p_fv*100:.1f}%', f'{exp_fv:.1f}%', f'{exp_final:.1f}%'
    ])

col_labels = ['N', 'K', 'g range', 'q_local', 'q_l/(g-1)', 'P_local',
              'P_fv(theory)', 'P_fv(exp)', 'P_final(exp)']
ax2b.axis('off')
table = ax2b.table(cellText=table_data, colLabels=col_labels,
                    loc='center', cellLoc='center')
table.auto_set_font_size(False)
table.set_fontsize(10)
table.scale(1.0, 1.8)

for j, label in enumerate(col_labels):
    table[0, j].set_facecolor('#2196F3')
    table[0, j].set_text_props(color='white', fontweight='bold')

for i in range(1, len(table_data) + 1):
    ratio = float(table_data[i-1][4])
    if ratio >= 1.0:
        for j in range(len(col_labels)):
            table[i, j].set_facecolor('#FFCDD2')
    elif ratio > 0.8:
        for j in range(len(col_labels)):
            table[i, j].set_facecolor('#FFF9C4')

ax2b.set_title('Concrete Examples: How Discrete Parameters Create the Oscillation',
               fontsize=13, pad=20)

plt.tight_layout()
fig2.savefig(os.path.join(base, 'fig_FINAL_bad_nodes.png'), bbox_inches='tight')
print("Saved: fig_FINAL_bad_nodes.png")

# ════════════════════════════════════════════════════════════
# FIGURE 3: The "3 gears" mechanism — intuitive explanation
# ════════════════════════════════════════════════════════════

fig3, axes3 = plt.subplots(3, 1, figsize=(18, 12), sharex=True)

ns_fine = list(range(16, 101))

# Gear 1: K = round(sqrt(N))
ax = axes3[0]
ks = [compute_groups(n)[0] for n in ns_fine]
ax.step(ns_fine, ks, where='mid', color='blue', linewidth=2.5)
for i in range(1, len(ns_fine)):
    if ks[i] != ks[i-1]:
        ax.axvline(ns_fine[i], color='red', alpha=0.4, linewidth=2)
        ax.annotate(f'K: {ks[i-1]}→{ks[i]}', xy=(ns_fine[i], ks[i]),
                   fontsize=8, color='red', fontweight='bold',
                   xytext=(ns_fine[i]+1, ks[i]+0.3))
ax.set_ylabel('K = round(√N)', fontsize=13, fontweight='bold')
ax.set_title('Gear 1: Branch Count K — Staircase Function', fontsize=14)
ax.grid(True, alpha=0.2)

# Gear 2: g = N/K (sawtooth)
ax = axes3[1]
avg_gs = [n / compute_groups(n)[0] for n in ns_fine]
min_gs_fine = [min(compute_groups(n)[1]) for n in ns_fine]
ax.plot(ns_fine, avg_gs, 'b-', linewidth=2, label='Avg group size (N/K)')
ax.plot(ns_fine, min_gs_fine, 'r-', linewidth=1.5, label='Min group size')
for i in range(1, len(ns_fine)):
    if ks[i] != ks[i-1]:
        ax.axvline(ns_fine[i], color='red', alpha=0.4, linewidth=2)
        ax.annotate(f'g drops!\n{avg_gs[i-1]:.1f}→{avg_gs[i]:.1f}',
                   xy=(ns_fine[i], avg_gs[i]),
                   fontsize=8, color='red',
                   xytext=(ns_fine[i]+1, avg_gs[i]-1.5),
                   arrowprops=dict(arrowstyle='->', color='red', lw=0.8))
ax.set_ylabel('Group Size g', fontsize=13, fontweight='bold')
ax.set_title('Gear 2: Group Size — Sawtooth Pattern (resets at each K jump)', fontsize=14)
ax.legend(fontsize=9)
ax.grid(True, alpha=0.2)

# Gear 3: Reliability (oscillates)
ax = axes3[2]
for dr, color, lw in [(90, '#F44336', 1.5), (95, '#4CAF50', 2), (98, '#2196F3', 1.5)]:
    sub = df[df['Delivery Rate (%)'] == dr].sort_values('Node Count (N)')
    if not sub.empty:
        ax.plot(sub['Node Count (N)'], sub['Raw Reliability'] * 100,
                'o-', color=color, markersize=3, linewidth=lw,
                label=f'Final Reliability DR={dr}%')
for i in range(1, len(ns_fine)):
    if ks[i] != ks[i-1]:
        ax.axvline(ns_fine[i], color='red', alpha=0.3, linewidth=2)

ax.set_xlabel('Node Count (N)', fontsize=13)
ax.set_ylabel('Reliability (%)', fontsize=13, fontweight='bold')
ax.set_title('Gear 3: Reliability — Oscillates in Response to K and g', fontsize=14)
ax.legend(fontsize=9)
ax.grid(True, alpha=0.2)
ax.set_ylim(-5, 110)

plt.tight_layout()
fig3.savefig(os.path.join(base, 'fig_FINAL_three_gears.png'), bbox_inches='tight')
print("Saved: fig_FINAL_three_gears.png")


# ════════════════════════════════════════════════════════════
# Print mathematical summary
# ════════════════════════════════════════════════════════════
print("""
╔══════════════════════════════════════════════════════════════════════════╗
║           MATHEMATICAL MODEL: Double-Layer HotStuff Reliability        ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                        ║
║  INPUT:  p = message delivery rate (0,1],  N = total node count        ║
║                                                                        ║
║  STEP 1 — Discrete Parameters:                                        ║
║    K = round(√N)                        ... branch (group) count       ║
║    f = ⌊(N-1)/3⌋                       ... global fault tolerance     ║
║    q_global = 2f + 1                    ... global quorum threshold    ║
║    g_j = ⌊N/K⌋ + [j < N mod K]        ... size of group j            ║
║    q_local_j = 2⌊(g_j-1)/3⌋ + 1       ... local quorum for group j   ║
║                                                                        ║
║  STEP 2 — Effective Delivery Probability:                              ║
║    p_eff = p^α    where α ≈ 3.73 (calibrated from 301 experiments)    ║
║                                                                        ║
║    α accounts for the multi-hop delivery chain in each vote:           ║
║    ① Leader → Group Leader broadcast (p)                               ║
║    ② Group Leader → Member forward (p)                                 ║
║    ③ Member → Group Leader vote reverse (p)                            ║
║    ④ Protocol overhead: async scheduling, view-check timing (~p^0.73)  ║
║                                                                        ║
║  STEP 3 — Per-Group Weight Distribution (per voting phase):            ║
║    X_j ~ Binomial(g_j - 1, p_eff)     ... # delivered member votes    ║
║    W_j^group = X_j · 𝟙[X_j ≥ q_local_j]   ... GroupVote weight       ║
║    W_j^GL ~ Bernoulli(p_eff)           ... Group Leader's direct vote  ║
║    W_j = W_j^group + W_j^GL            ... total weight from group j   ║
║    (For the root group: W_j^GL = 0, root doesn't self-vote)            ║
║                                                                        ║
║  STEP 4 — Single Phase Success Probability:                            ║
║    P_phase(p,N) = P(∑_{j=0}^{K-1} W_j ≥ q_global)                    ║
║    [Computed via PMF convolution of independent W_j's]                 ║
║                                                                        ║
║  STEP 5 — First-View Reliability:                                      ║
║    P_fv(p,N) = [P_phase(p,N)]³                                        ║
║    (HotStuff requires 3 consecutive phases: prepare, pre-commit, commit)║
║                                                                        ║
║  STEP 6 — Final Reliability (with View Change):                        ║
║    P_final(p,N) = 1 - [1 - P_fv(p,N)]^V                              ║
║    where V ≈ 14 views within the timeout window                        ║
║                                                                        ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                        ║
║  WHY THE OSCILLATION HAPPENS — "Three Gears" Mechanism:               ║
║                                                                        ║
║  Gear 1: K = round(√N)                                                ║
║    ⮕ K is a STAIRCASE function. Jumps at N ≈ 20, 30, 42, 56, 72, 90  ║
║                                                                        ║
║  Gear 2: g = N/K                                                      ║
║    ⮕ g is a SAWTOOTH wave. After each K jump, g drops suddenly,       ║
║      then slowly recovers as N increases within the K plateau.         ║
║                                                                        ║
║  Gear 3: q_local = 2⌊(g-1)/3⌋ + 1                                   ║
║    ⮕ q_local is ANOTHER staircase. When g drops past a threshold      ║
║      (g: 7→6 doesn't change q_local, but g: 10→7 DOES), the quorum   ║
║      requirement may stay the same while the group got smaller.        ║
║                                                                        ║
║  The ratio q_local/(g-1) determines difficulty:                        ║
║    • < 0.67: easy (always passes with high p)                          ║
║    • 0.67–0.85: moderate (sensitive to p)                              ║
║    • > 0.85: hard (needs ALL or almost ALL votes)                      ║
║    • ≥ 1.0: IMPOSSIBLE (more votes needed than voters exist)           ║
║                                                                        ║
║  The oscillation cycle:                                                ║
║    K jumps → g drops → ratio rises → P_local drops → reliability ↓    ║
║    N grows → g recovers → ratio falls → P_local rises → reliability ↑ ║
║                                                                        ║
║  DR modulates the AMPLITUDE:                                           ║
║    • p ≥ 0.98: P_local ≈ 1 even for hard groups → nearly flat at 100% ║
║    • p ≈ 0.95: clear oscillation, ~70-100%                             ║
║    • p ≈ 0.90: extreme oscillation, ~3-70%                             ║
║    • p ≤ 0.88: system unreliable regardless of N                       ║
║                                                                        ║
╚══════════════════════════════════════════════════════════════════════════╝
""")
