"""
Calibrate the mathematical model by finding optimal p_eff exponent
and comparing multiple model variants against experimental data.
"""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import math
import os
from scipy.stats import binom
from scipy.optimize import minimize_scalar

base = os.path.dirname(__file__)
plt.rcParams.update({
    'font.size': 11, 'axes.titlesize': 13, 'axes.labelsize': 12,
    'legend.fontsize': 9, 'figure.dpi': 150, 'savefig.dpi': 200,
})

# ── Load data ──
csvs = [
    os.path.join(base, 'Experiment2_Phase2_N16_80_DR95_98_99_R1000.csv'),
    os.path.join(base, 'Experiment2_Phase3_N16_100_DR90_92_94_95_96_R1000.csv'),
]
frames = [pd.read_csv(c) for c in csvs if os.path.exists(c)]
df = pd.concat(frames, ignore_index=True)
df = df.drop_duplicates(subset=['Delivery Rate (%)', 'Node Count (N)'], keep='last')
df = df.sort_values(['Delivery Rate (%)', 'Node Count (N)'])

# ── Model functions ──

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
    f_local = (g - 1) // 3
    return 2 * f_local + 1

def P_single_phase(N, p_percent, alpha=2.0):
    """P(single voting phase succeeds) with p_eff = (p/100)^alpha"""
    K, groups, f, q_global = compute_global_params(N)
    p = p_percent / 100.0
    p_eff = p ** alpha

    def group_weight_pmf(g, is_root_group):
        n_voters = g - 1
        q_local = compute_local_threshold(g)
        pmf = {}
        for k in range(n_voters + 1):
            prob = binom.pmf(k, n_voters, p_eff)
            w_group = k if k >= q_local else 0
            if not is_root_group:
                for gl_vote in [0, 1]:
                    gl_prob = p_eff if gl_vote == 1 else (1 - p_eff)
                    total_w = w_group + gl_vote
                    pmf[total_w] = pmf.get(total_w, 0.0) + prob * gl_prob
            else:
                pmf[w_group] = pmf.get(w_group, 0.0) + prob
        return pmf

    def convolve(pmf1, pmf2):
        result = {}
        for w1, p1 in pmf1.items():
            for w2, p2 in pmf2.items():
                w = w1 + w2
                result[w] = result.get(w, 0.0) + p1 * p2
        return result

    total_pmf = group_weight_pmf(groups[0], is_root_group=True)
    for j in range(1, len(groups)):
        total_pmf = convolve(total_pmf, group_weight_pmf(groups[j], is_root_group=False))
    return sum(p for w, p in total_pmf.items() if w >= q_global)


def P_first_view(N, p_percent, alpha=2.0):
    return P_single_phase(N, p_percent, alpha) ** 3


def P_final(N, p_percent, alpha=2.0, max_views=3):
    pf = P_first_view(N, p_percent, alpha)
    return 1 - (1 - pf) ** max_views


# ── Calibrate alpha ──

print("Calibrating alpha (p_eff = p^alpha) against first-view data...")

def loss(alpha):
    total_err = 0.0
    count = 0
    for _, row in df.iterrows():
        N = int(row['Node Count (N)'])
        dr = int(row['Delivery Rate (%)'])
        fv_exp = float(row.get('First-View Raw Reliability', 0))
        if fv_exp == 0 and dr <= 90:
            continue
        fv_theory = P_first_view(N, dr, alpha)
        total_err += (fv_theory - fv_exp) ** 2
        count += 1
    return total_err / max(count, 1)

result = minimize_scalar(loss, bounds=(1.5, 4.5), method='bounded')
alpha_opt = result.x
print(f"Optimal alpha = {alpha_opt:.4f} (MSE = {result.fun:.6f})")

# Also compute MSE for alpha = 2, 3, 4
for a in [2.0, 3.0, alpha_opt, 4.0]:
    mse = loss(a)
    print(f"  alpha={a:.2f} → MSE={mse:.6f}")

# ── Compute predictions for all models ──

rows = []
for _, row in df.iterrows():
    N = int(row['Node Count (N)'])
    dr = int(row['Delivery Rate (%)'])
    K, groups, f, q_global = compute_global_params(N)

    d = {
        'N': N, 'DR': dr, 'K': K, 'f': f, 'q_global': q_global,
        'P_fv_exp': float(row.get('First-View Raw Reliability', 0)),
        'P_final_exp': float(row['Raw Reliability']),
    }
    for a, label in [(2.0, 'a2'), (3.0, 'a3'), (alpha_opt, 'aopt')]:
        d[f'P_phase_{label}'] = P_single_phase(N, dr, a)
        d[f'P_fv_{label}'] = P_first_view(N, dr, a)
        d[f'P_final3_{label}'] = P_final(N, dr, a, max_views=3)
        d[f'P_final5_{label}'] = P_final(N, dr, a, max_views=5)
    rows.append(d)

tdf = pd.DataFrame(rows)

# ── Compute correlation ──

for a, label in [(2.0, 'a2'), (3.0, 'a3'), (alpha_opt, 'aopt')]:
    r_fv = np.corrcoef(tdf['P_fv_exp'], tdf[f'P_fv_{label}'])[0, 1]
    r_final = np.corrcoef(tdf['P_final_exp'], tdf[f'P_final3_{label}'])[0, 1]
    print(f"alpha={a:.2f}: R(first-view)={r_fv:.4f}, R(final,3views)={r_final:.4f}")

# ════════════════════════════════════════════════════════════
# FIGURE 1: Scatter — Theory vs Experiment (First-View, all alpha)
# ════════════════════════════════════════════════════════════

fig1, axes = plt.subplots(1, 3, figsize=(18, 5))
for idx, (a, label, name) in enumerate([
    (2.0, 'a2', r'$\alpha=2$ ($p_{eff}=p^2$)'),
    (3.0, 'a3', r'$\alpha=3$ ($p_{eff}=p^3$)'),
    (alpha_opt, 'aopt', fr'$\alpha={alpha_opt:.2f}$ (optimal)'),
]):
    ax = axes[idx]
    for dr in sorted(tdf['DR'].unique()):
        sub = tdf[tdf['DR'] == dr]
        ax.scatter(sub[f'P_fv_{label}'] * 100, sub['P_fv_exp'] * 100,
                   s=12, alpha=0.6, label=f'DR={dr}%')
    ax.plot([0, 100], [0, 100], 'k--', alpha=0.3, linewidth=1)
    r = np.corrcoef(tdf['P_fv_exp'], tdf[f'P_fv_{label}'])[0, 1]
    mse = np.mean((tdf['P_fv_exp'] - tdf[f'P_fv_{label}']) ** 2)
    ax.set_title(f'{name}\nR={r:.3f}, MSE={mse:.4f}')
    ax.set_xlabel('Theory (%)')
    ax.set_ylabel('Experiment (%)')
    ax.set_xlim(-5, 105)
    ax.set_ylim(-5, 105)
    ax.grid(True, alpha=0.2)
    ax.legend(fontsize=6, loc='upper left')
    ax.set_aspect('equal')
plt.suptitle('First-View Reliability: Theory vs Experiment', fontsize=14, y=1.02)
plt.tight_layout()
fig1.savefig(os.path.join(base, 'fig_calibration_scatter.png'), bbox_inches='tight')
print("Saved: fig_calibration_scatter.png")

# ════════════════════════════════════════════════════════════
# FIGURE 2: Per-DR comparison with calibrated model
# ════════════════════════════════════════════════════════════

drs = sorted(tdf['DR'].unique())
fig2, axes2 = plt.subplots(len(drs), 1, figsize=(16, 3.5 * len(drs)), sharex=True)
if len(drs) == 1:
    axes2 = [axes2]

for idx, dr in enumerate(drs):
    ax = axes2[idx]
    sub = tdf[tdf['DR'] == dr].sort_values('N')
    ax.plot(sub['N'], sub['P_fv_exp'] * 100, 'o-', markersize=4, linewidth=1.5,
            color='#2196F3', label='Experiment (First-View)', zorder=5)
    ax.plot(sub['N'], sub[f'P_fv_aopt'] * 100, 's--', markersize=3, linewidth=1.2,
            color='#F44336', label=fr'Theory $\alpha$={alpha_opt:.2f}')
    ax.plot(sub['N'], sub['P_fv_a2'] * 100, '^:', markersize=2.5, linewidth=0.8,
            color='#9E9E9E', alpha=0.5, label=r'Theory $\alpha$=2')
    ax.set_ylabel(f'DR={dr}%\nFirst-View (%)')
    ax.legend(loc='upper right', fontsize=7)
    ax.grid(True, alpha=0.3)
    ax.set_ylim(-5, 110)

axes2[-1].set_xlabel('Node Count (N)')
axes2[0].set_title(fr'First-View Reliability: Calibrated Model ($\alpha$={alpha_opt:.2f})')
plt.tight_layout()
fig2.savefig(os.path.join(base, 'fig_calibrated_firstview.png'), bbox_inches='tight')
print("Saved: fig_calibrated_firstview.png")

# ════════════════════════════════════════════════════════════
# FIGURE 3: Final reliability with calibrated model + view sweep
# ════════════════════════════════════════════════════════════

fig3, axes3 = plt.subplots(len(drs), 1, figsize=(16, 3.5 * len(drs)), sharex=True)
if len(drs) == 1:
    axes3 = [axes3]

# Find best max_views for final reliability
best_views = {}
for v in range(1, 15):
    col = f'_pf_{v}'
    tdf[col] = tdf.apply(lambda r: P_final(int(r['N']), int(r['DR']), alpha_opt, v), axis=1)
    mse = np.mean((tdf['P_final_exp'] - tdf[col]) ** 2)
    best_views[v] = mse
    if v <= 5:
        print(f"  max_views={v}: final MSE = {mse:.6f}")

best_v = min(best_views, key=best_views.get)
print(f"Best max_views for final reliability: {best_v} (MSE={best_views[best_v]:.6f})")

for idx, dr in enumerate(drs):
    ax = axes3[idx]
    sub = tdf[tdf['DR'] == dr].sort_values('N')
    ax.plot(sub['N'], sub['P_final_exp'] * 100, 'o-', markersize=4, linewidth=1.5,
            color='#2196F3', label='Experiment (Final)')
    ax.plot(sub['N'], sub[f'_pf_{best_v}'] * 100, 's--', markersize=3, linewidth=1.2,
            color='#F44336', label=fr'Theory (V={best_v}, $\alpha$={alpha_opt:.2f})')
    ax.set_ylabel(f'DR={dr}%\nFinal (%)')
    ax.legend(loc='lower right', fontsize=7)
    ax.grid(True, alpha=0.3)
    ax.set_ylim(-5, 110)

axes3[-1].set_xlabel('Node Count (N)')
axes3[0].set_title(fr'Final Reliability: Calibrated Model ($\alpha$={alpha_opt:.2f}, V={best_v})')
plt.tight_layout()
fig3.savefig(os.path.join(base, 'fig_calibrated_final.png'), bbox_inches='tight')
print("Saved: fig_calibrated_final.png")

# ════════════════════════════════════════════════════════════
# FIGURE 4: Oscillation anatomy — why specific N values are bad
# ════════════════════════════════════════════════════════════

fig4, (ax4a, ax4b) = plt.subplots(2, 1, figsize=(16, 10))

# Panel A: For DR=95%, show P_local for each group, highlighting the weakest
ns = list(range(16, 101))
for dr in [90, 95]:
    p_eff = (dr / 100.0) ** alpha_opt
    weakest_local = []
    strongest_local = []
    for N in ns:
        K, groups, f, q_global = compute_global_params(N)
        probs = []
        for g in groups:
            q_local = compute_local_threshold(g)
            n_v = g - 1
            if n_v < q_local:
                probs.append(0.0)
            else:
                probs.append(1 - binom.cdf(q_local - 1, n_v, p_eff))
        weakest_local.append(min(probs))
        strongest_local.append(max(probs))
    
    ax4a.plot(ns, [p * 100 for p in weakest_local], 'o-', markersize=3, linewidth=1.2,
              label=f'Weakest group P_local (DR={dr}%)')
    ax4a.fill_between(ns,
                       [p * 100 for p in weakest_local],
                       [p * 100 for p in strongest_local],
                       alpha=0.15)

ax4a.set_ylabel('Local Quorum Pass Probability (%)')
ax4a.set_title(fr'Per-Group Local Quorum Probability ($\alpha$={alpha_opt:.2f})')
ax4a.legend(loc='lower right')
ax4a.grid(True, alpha=0.3)
ax4a.set_ylim(-5, 110)

# Panel B: The "quorum difficulty ratio" q_local / (g-1) drives oscillation
for N in ns:
    K, groups, f, q_global = compute_global_params(N)
    min_g = min(groups)
    q_local = compute_local_threshold(min_g)
    n_v = min_g - 1
    ratio = q_local / max(n_v, 1)
    color = 'red' if ratio > 0.85 else ('orange' if ratio > 0.75 else 'green')
    ax4b.bar(N, ratio, width=1.8, color=color, alpha=0.7, edgecolor='none')

ax4b.axhline(2/3, color='blue', linewidth=1, linestyle='--', alpha=0.5,
             label='Theoretical BFT minimum (2/3)')
ax4b.axhline(1.0, color='red', linewidth=1, linestyle=':', alpha=0.5,
             label='Impossible (ratio ≥ 1)')
ax4b.set_xlabel('Node Count (N)')
ax4b.set_ylabel('q_local / (g-1)')
ax4b.set_title('Quorum Difficulty Ratio (smallest group)\nRed = very hard, Green = easy')
ax4b.legend(loc='upper left', fontsize=8)
ax4b.grid(True, alpha=0.3)
ax4b.set_ylim(0.5, 1.15)

plt.tight_layout()
fig4.savefig(os.path.join(base, 'fig_oscillation_anatomy.png'), bbox_inches='tight')
print("Saved: fig_oscillation_anatomy.png")

# ════════════════════════════════════════════════════════════
# Print the complete formula with calibrated alpha
# ════════════════════════════════════════════════════════════

print(f"""
════════════════════════════════════════════════════════════════
       CALIBRATED MATHEMATICAL MODEL (α = {alpha_opt:.4f})
════════════════════════════════════════════════════════════════

The effective per-vote delivery probability:

    p_eff = p^{alpha_opt:.2f}

This accounts for the multiple independent delivery checks each vote
undergoes in the double-layer HotStuff protocol:
  1. Forward delivery: Leader/QC broadcast to replica (p)
  2. Reverse delivery: Replica vote back to collector (p)
  3. Protocol overhead: async scheduling, timing jitter (~p^{alpha_opt - 2:.2f})

COMPLETE FORMULA:
─────────────────────────────────────────────────────────────

Given: p (delivery rate), N (node count)

Step 1 — Discrete parameters:
    K = round(√N)
    f = ⌊(N-1)/3⌋
    q_global = 2f + 1
    For each group j: g_j, q_local_j = 2⌊(g_j-1)/3⌋ + 1

Step 2 — Per-group weight distribution W_j:
    Members vote: X_j ~ Binomial(g_j - 1, p^{alpha_opt:.2f})
    GroupVote weight = X_j if X_j ≥ q_local_j, else 0
    GL self-vote (non-root): Bernoulli(p^{alpha_opt:.2f}), adds +1

Step 3 — Single phase:
    P_phase = P(∑_j W_j ≥ q_global)    [via convolution]

Step 4 — First-view reliability:
    P_first_view = P_phase³

Step 5 — Final reliability:
    P_final = 1 - (1 - P_first_view)^V     [V ≈ {best_v} views]

════════════════════════════════════════════════════════════════
""")
