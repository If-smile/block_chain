"""
Double-Layer HotStuff Reliability Mathematical Model
=====================================================

Derives P_final(p, N) from first principles based on the actual code logic:

Architecture:
  - N nodes split into K = round(sqrt(N)) groups
  - Groups use fair partition: first (N%K) groups have ceil(N/K) nodes, rest have floor(N/K)
  - Global Leader = view % N  (rotates each view)
  - Phase pipeline: prepare -> pre-commit -> commit -> decide  (3 voting rounds)

Per voting round, two layers of message delivery:
  Layer 1 (Local): Members vote -> Group Leader
    - Each vote has TWO independent delivery checks (forward + reverse), effective p_eff = p^2
    - Group j passes if #delivered_votes >= q_local_j = 2*floor((g_j - 1)/3) + 1
    - Note: the Group Leader itself doesn't vote to itself, so g_j - 1 members vote

  Layer 2 (Global): Group Leaders send GroupVote -> Global Leader
    - GroupVote carries weight = #local_votes collected
    - Global Leader needs total_weight >= q_global = 2*floor((N-1)/3) + 1
    
Message loss model:
  - should_deliver_message() is called TWICE per vote:
    1. Forward: Leader broadcasts QC/proposal to replica  (in trigger_robot_votes line 262)
    2. Reverse: Replica sends vote back                    (in trigger_robot_votes line 271)
  - Both must succeed for the vote to count: effective per-vote delivery = p^2

  - For Proposal broadcast (robot_send_pre_prepare):
    - Global Leader -> Group Leaders: one check per GL
    - Group Leader -> Members: one check per member  
    - Members who don't receive proposal don't vote at all

  - For subsequent voting rounds (trigger_robot_votes):
    - Forward drop + Reverse drop = p^2 per vote
"""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import math
import os
from scipy.stats import binom
from itertools import product

base = os.path.dirname(__file__)

plt.rcParams.update({
    'font.size': 11,
    'axes.titlesize': 13,
    'axes.labelsize': 12,
    'legend.fontsize': 9,
    'figure.dpi': 150,
    'savefig.dpi': 200,
})

# ════════════════════════════════════════════════════════════
# STEP 1: Exact parameter computation (mirrors the code)
# ════════════════════════════════════════════════════════════

def compute_groups(N):
    """Mirrors _build_groups in topology_manager.py"""
    K = max(1, round(math.sqrt(N)))
    base_size = N // K
    remainder = N % K
    groups = []
    for gid in range(K):
        g = base_size + 1 if gid < remainder else base_size
        groups.append(g)
    return K, groups

def compute_global_params(N):
    K, groups = compute_groups(N)
    f = (N - 1) // 3
    q_global = 2 * f + 1
    return K, groups, f, q_global

def compute_local_threshold(g):
    """Mirrors get_local_quorum_threshold"""
    f_local = (g - 1) // 3
    return 2 * f_local + 1

# ════════════════════════════════════════════════════════════
# STEP 2: Probability of a single group passing local quorum
# ════════════════════════════════════════════════════════════

def P_group_pass(g, p_eff):
    """
    Probability that a group of size g passes local quorum.
    
    In a group:
      - 1 node is the Group Leader (collects votes, doesn't vote to itself)
      - g-1 nodes are Members who each vote with success prob p_eff
      - Need >= q_local = 2*floor((g-1)/3) + 1 successful votes
    
    This is: P(Binomial(g-1, p_eff) >= q_local)
    """
    q_local = compute_local_threshold(g)
    n_voters = g - 1
    if n_voters < 0:
        return 0.0
    if q_local <= 0:
        return 1.0
    if n_voters < q_local:
        return 0.0
    return 1.0 - binom.cdf(q_local - 1, n_voters, p_eff)

# ════════════════════════════════════════════════════════════
# STEP 3: Probability of passing global quorum
# ════════════════════════════════════════════════════════════

def P_single_phase(N, p):
    """
    Probability that a single voting phase succeeds.
    
    Each vote undergoes two delivery checks: p_eff = p^2
    
    For each group j (size g_j):
      - P(group j passes) = P(Binom(g_j - 1, p_eff) >= q_local_j)
      - If passes, contributes weight w_j = E[votes | passed] ~ but in code,
        weight = actual count of delivered votes
    
    For global quorum: sum of weights across passing groups >= q_global
    
    This is a complex joint distribution. We compute it via convolution.
    """
    K, groups, f, q_global = compute_global_params(N)
    p_eff = (p / 100.0) ** 2
    
    # For the proposal delivery phase, there's an additional p check
    # But in the prepare phase (first voting round), robots that didn't
    # receive the proposal don't vote. This is handled by robot_send_prepare_messages
    # line 429: `if not should_deliver_message(session_id): continue`
    # So effectively each member has 3 checks: proposal delivery, forward, reverse
    # => p_eff_first_round = p^3 for prepare phase
    # For subsequent phases (pre-commit, commit), the QC broadcast also has a
    # forward delivery check, so it's still p^2 for the vote + p for receiving QC
    # => p_eff = p^3 for all phases
    
    # Actually, let me re-read the code more carefully:
    # In robot_send_prepare_messages (line 429):
    #   - `if not should_deliver_message(session_id): continue` -- this is the proposal receipt check
    # In trigger_robot_votes (lines 262, 271):
    #   - Line 262: `if not should_deliver_message(session_id): continue` -- forward drop
    #   - Line 271: `delivered = should_deliver_message(session_id)` -- reverse drop
    # 
    # So for prepare phase:
    #   P(member votes successfully) = P(received proposal) * P(forward) * P(reverse) = p^3
    # For pre-commit and commit phases (triggered by trigger_robot_votes):
    #   P(member votes successfully) = P(forward) * P(reverse) = p^2
    #   (They already received the QC because trigger_robot_votes handles both)
    #   Wait, no - trigger_robot_votes line 262 is the "forward" which represents
    #   "Leader broadcasts QC to Replica", and line 271 is "Replica sends vote back"
    #   So for ALL phases via trigger_robot_votes, it's p^2 per vote.
    #
    # For prepare phase via robot_send_prepare_messages:
    #   Each member: P(proposal received) * 1 check for handle_proposal_message_cb
    #   Then handle_robot_prepare -> handle_robot_prepare (line 455): should_deliver_message
    #   That's p (proposal) * p (prepare vote delivery) = p^2
    #
    # Actually let me trace more carefully:
    # robot_send_prepare_messages line 429: should_deliver -> skip if false (proposal receipt)
    # robot_send_prepare_messages line 432: handle_proposal_message_cb -> schedule_robot_prepare
    # handle_robot_prepare line 455: delivered = should_deliver_message(session_id)
    # So prepare phase: p (proposal receipt) * p (vote delivery) = p^2
    #
    # trigger_robot_votes (for pre-commit, commit):
    # line 262: should_deliver_message -> forward drop  
    # line 271: should_deliver_message -> reverse drop
    # So: p * p = p^2
    #
    # BUT the proposal itself also needs delivery:
    # robot_send_pre_prepare sends proposal to Group Leaders (line 320: should_deliver)
    # and Group Leaders forward to Members (line 343: should_deliver)
    # So proposal reaching a member = p (GL receives) * p (member receives) = p^2
    # Then member receiving proposal: p^2
    # Then member voting in prepare: p (from robot_send_prepare line 429) * p (handle_robot_prepare line 455) = p^2
    # Total for prepare = p^2 * p^2 = p^4 ? No wait...
    #
    # Hmm, the prepare messages line 429 is a SEPARATE check from the proposal broadcast.
    # Line 429 simulates "did this member actually receive the proposal" - it's a THIRD check.
    # But wait, the proposal was ALREADY broadcast in robot_send_pre_prepare with its own checks.
    # The line 429 check is an ADDITIONAL, INDEPENDENT simulation of proposal receipt.
    #
    # Let me re-examine: robot_send_pre_prepare broadcasts the proposal message to GLs and members
    # with should_deliver_message checks. But those emit to Socket.IO rooms - in simulation mode,
    # nodes are robots with no actual sockets. The socket emission doesn't affect vote logic.
    # What matters is the should_deliver check in robot_send_prepare_messages.
    #
    # So the ACTUAL vote path for prepare:
    #   1. robot_send_prepare_messages line 429: should_deliver_message -> p
    #   2. handle_robot_prepare line 455: should_deliver_message -> p
    #   => P(prepare vote counts) = p^2
    #
    # For pre-commit and commit (trigger_robot_votes):
    #   1. line 262: should_deliver_message -> p (forward)
    #   2. line 271: should_deliver_message -> p (reverse)
    #   => P(vote counts) = p^2
    #
    # All three phases have p_eff = p^2. Good.
    
    p_eff = (p / 100.0) ** 2
    
    # We need P(sum of weights across groups >= q_global)
    # where each group independently contributes a random weight.
    #
    # For group j with size g_j:
    #   Number of successful votes ~ Binomial(g_j - 1, p_eff)
    #   If votes >= q_local_j, group passes and weight = #votes
    #   If votes < q_local_j, group contributes weight 0
    #
    # Actually, re-reading the code in consensus_service.py:
    # When _process_member_vote fires with enough votes, it creates a GroupVote with
    # weight = len(group_voters). Then _process_global_vote adds this weight.
    # 
    # But also: Group Leaders that are also the Global Leader have role "root",
    # and in trigger_robot_votes, "root" nodes skip voting (line 143 of robot_agent:
    # `if node_info["role"] == "root": return None`)
    #
    # And Group Leaders that are NOT root: they have role "group_leader" and they
    # DO vote. But their vote goes directly to Global Leader with weight 1.
    # Wait - in handle_vote (consensus_service line 491):
    #   if voter_role in ("group_leader", "root"): _process_global_vote
    # So Group Leaders' own votes go directly to global aggregation with weight 1.
    #
    # So the full picture per phase:
    # For each group j:
    #   - Members (g_j - 1 nodes, excluding GL) vote to Group Leader
    #   - If >= q_local_j members' votes delivered, Group Leader generates GroupVote 
    #     with weight = #delivered votes
    #   - This GroupVote goes to Global Leader (with its own delivery check? 
    #     Let me check... In handle_vote line 622, consensus_service.handle_vote
    #     is called with the vote_message. When a member vote triggers a GroupVote,
    #     the GroupVote is IMMEDIATELY processed globally in the SAME call
    #     (line 470-475 of consensus_service). No additional delivery check!
    #   
    #   - Additionally, Group Leaders themselves vote (in trigger_robot_votes),
    #     with their own forward+reverse checks (p^2). Their vote has weight 1
    #     and goes directly to Global Leader.
    #
    # Wait, but the GroupVote's delivery to Global Leader... In socket_handlers.py
    # handle_vote function (line 634):
    #   if group_vote:
    #     global_leader_id = group_vote["to"]
    # Then line 638-656 shows the GroupVote being sent via socket to Global Leader
    # with should_deliver_message checks (line 643, 649).
    # 
    # Hmm actually let me re-read socket_handlers.py handle_vote more carefully.
    
    # Actually, the key insight is:
    # The GroupVote generated by _process_member_vote is ALSO immediately 
    # processed by _process_global_vote in the SAME call chain (consensus_service
    # line 470). The socket emission in socket_handlers is just for frontend display.
    # The actual consensus logic all happens in consensus_service.handle_vote().
    #
    # So there's NO additional delivery check for the GroupVote path!
    # 
    # But Group Leaders' own direct votes DO go through trigger_robot_votes
    # with p^2 delivery chance.
    #
    # Summary per phase:
    # For group j (size g_j, Group Leader = GL_j):
    #   - (g_j - 1) members each vote with success prob p^2
    #   - If #successes >= q_local_j: group contributes weight = #successes to global
    #   - GL_j also votes directly to Global Leader with prob p^2, contributing weight 1
    #   - BUT: if GL_j is the Global Leader (root), GL_j doesn't vote
    #
    # Global success: sum of all contributions >= q_global = 2*floor((N-1)/3) + 1
    #
    # Since the Global Leader's group has the Global Leader as its "leader",
    # and the Global Leader doesn't vote to itself, that group's GL IS the root.
    # Members of that group still vote to root, contributing their weights.
    # But the root doesn't cast its own vote.
    #
    # For OTHER groups: GL votes with p^2 (contributing weight 1) AND
    # members' aggregated GroupVote contributes weight = delivered count (if >= q_local).

    # For simplicity and because we average over views (leader rotates),
    # we can compute P for a specific view=0 (leader = node 0) and note that
    # statistically all views are equivalent (groups are fixed, leader rotates).
    # Actually leader rotation changes which group has the root, which slightly
    # changes the math. But since we're averaging over 1000 rounds with view changes,
    # the effect is averaged. Let's compute for the "typical" case.
    #
    # SIMPLIFICATION: 
    # Treat each group as contributing a random weight:
    #   W_j ~ Binomial(g_j - 1, p_eff) if the GL is root (no GL self-vote)  
    #   W_j ~ Binomial(g_j - 1, p_eff) + Bernoulli(p_eff) if GL is not root
    # (where group passes local quorum for the Binomial part)
    #
    # Actually, the GroupVote weight is only added to global IF the group passes
    # local quorum. If it doesn't, the member votes are essentially wasted.
    # The GL's own vote goes through regardless (as a direct vote).
    #
    # So:
    #   For non-root GL group: W_j = GroupVote_weight (if local quorum met, else 0) + GL_vote (Bernoulli(p_eff))
    #   For root group: W_j = GroupVote_weight (if local quorum met, else 0)
    
    # This is getting complex. Let me implement it properly via convolution.
    # We compute the PMF of total weight as the convolution of per-group weight PMFs.
    
    # For tractability, assume view=0, so node 0 is root, which is in group 0.
    
    # Per-group weight PMF:
    def group_weight_pmf(g, is_root_group, p_eff):
        """Returns dict {weight: probability}"""
        n_voters = g - 1  # members who vote
        q_local = compute_local_threshold(g)
        
        pmf = {}
        
        # Component 1: GroupVote weight
        # Binomial(n_voters, p_eff), but only counts if >= q_local
        for k in range(n_voters + 1):
            prob = binom.pmf(k, n_voters, p_eff)
            if k >= q_local:
                w_group = k
            else:
                w_group = 0
            
            if not is_root_group:
                # Component 2: GL's own vote (Bernoulli(p_eff))
                # GL vote succeeds with prob p_eff, contributing +1
                for gl_vote in [0, 1]:
                    gl_prob = p_eff if gl_vote == 1 else (1 - p_eff)
                    total_w = w_group + gl_vote
                    pmf[total_w] = pmf.get(total_w, 0.0) + prob * gl_prob
            else:
                # Root group: no GL self-vote
                pmf[w_group] = pmf.get(w_group, 0.0) + prob
        
        return pmf
    
    def convolve_pmfs(pmf1, pmf2):
        """Convolve two PMFs (dict form)"""
        result = {}
        for w1, p1 in pmf1.items():
            for w2, p2 in pmf2.items():
                w = w1 + w2
                result[w] = result.get(w, 0.0) + p1 * p2
        return result
    
    # Build per-group PMFs and convolve
    # Root is in group 0 (for view=0, node 0 is root, and node 0 is always in group 0)
    group_pmfs = []
    for j, g in enumerate(groups):
        is_root = (j == 0)
        pmf = group_weight_pmf(g, is_root, p_eff)
        group_pmfs.append(pmf)
    
    # Convolve all group PMFs
    total_pmf = group_pmfs[0]
    for j in range(1, len(group_pmfs)):
        total_pmf = convolve_pmfs(total_pmf, group_pmfs[j])
    
    # P(total_weight >= q_global)
    prob = sum(p for w, p in total_pmf.items() if w >= q_global)
    return prob


def P_first_view(N, p):
    """
    Probability of consensus in the first view (no view change).
    HotStuff has 3 voting phases: prepare, pre-commit, commit.
    All three must succeed for first-view consensus.
    
    P_first_view = P_single_phase^3
    """
    p_phase = P_single_phase(N, p)
    return p_phase ** 3


def P_final(N, p, max_views=10):
    """
    Probability of eventual consensus (allowing view changes).
    
    If first view fails, HotStuff triggers a view change and tries with a new leader.
    P_final = 1 - (1 - P_first_view)^max_views
    
    In the simulation, max_round_wait_seconds = 3.0 with 0.001s delays,
    so roughly 2-3 views can be attempted.
    """
    p_fv = P_first_view(N, p)
    # Estimate how many views can fit in max_round_wait_seconds
    # Each view takes roughly: proposal broadcast + 3 phases of voting
    # In simulation: delays are 0.001s, plus async overhead
    # Roughly 3-5 views possible in 3 seconds
    p_fail_all = (1 - p_fv) ** max_views
    return 1 - p_fail_all


# ════════════════════════════════════════════════════════════
# STEP 4: Load experimental data and compare
# ════════════════════════════════════════════════════════════

csvs = [
    os.path.join(base, 'Experiment2_Phase2_N16_80_DR95_98_99_R1000.csv'),
    os.path.join(base, 'Experiment2_Phase3_N16_100_DR90_92_94_95_96_R1000.csv'),
]
frames = []
for c in csvs:
    if os.path.exists(c):
        frames.append(pd.read_csv(c))
df = pd.concat(frames, ignore_index=True)
df = df.drop_duplicates(subset=['Delivery Rate (%)', 'Node Count (N)'], keep='last')
df = df.sort_values(['Delivery Rate (%)', 'Node Count (N)'])

# Compute theoretical predictions
theory_rows = []
for _, row in df.iterrows():
    N = int(row['Node Count (N)'])
    dr = int(row['Delivery Rate (%)'])
    p_fv_theory = P_first_view(N, dr)
    p_phase_theory = P_single_phase(N, dr)
    
    # For final reliability, calibrate max_views from data
    # Typical simulation allows ~3-5 view changes in 3 seconds
    p_final_3 = P_final(N, dr, max_views=3)
    p_final_5 = P_final(N, dr, max_views=5)
    
    K, groups, f, q_global = compute_global_params(N)
    
    theory_rows.append({
        'N': N, 'DR': dr,
        'K': K, 'f': f, 'q_global': q_global,
        'groups': str(groups),
        'P_phase': p_phase_theory,
        'P_first_view_theory': p_fv_theory,
        'P_final_3views': p_final_3,
        'P_final_5views': p_final_5,
        'P_first_view_exp': row.get('First-View Raw Reliability', 0),
        'P_final_exp': row['Raw Reliability'],
    })

tdf = pd.DataFrame(theory_rows)
tdf.to_csv(os.path.join(base, 'theory_vs_experiment.csv'), index=False)
print("Saved: theory_vs_experiment.csv")

# ════════════════════════════════════════════════════════════
# FIGURE A: Theory vs Experiment — First-View Reliability
# ════════════════════════════════════════════════════════════

drs_to_plot = sorted(tdf['DR'].unique())
cmap = plt.cm.RdYlGn
dr_colors = {dr: cmap((dr - 88) / 14) for dr in drs_to_plot}

fig_a, axes_a = plt.subplots(len(drs_to_plot), 1, figsize=(16, 4 * len(drs_to_plot)),
                              sharex=True)
if len(drs_to_plot) == 1:
    axes_a = [axes_a]

for idx, dr in enumerate(drs_to_plot):
    ax = axes_a[idx]
    sub = tdf[tdf['DR'] == dr].sort_values('N')
    ax.plot(sub['N'], sub['P_first_view_exp'] * 100,
            'o-', markersize=4, linewidth=1.5, color='#2196F3',
            label='Experiment (First-View)')
    ax.plot(sub['N'], sub['P_first_view_theory'] * 100,
            's--', markersize=3, linewidth=1.2, color='#F44336',
            label='Theory: $p_{eff}=p^2$, $P_{fv}=P_{phase}^3$')
    ax.set_ylabel(f'DR={dr}%\nReliability (%)')
    ax.legend(loc='upper right', fontsize=8)
    ax.grid(True, alpha=0.3)
    ax.set_ylim(-5, 110)

axes_a[-1].set_xlabel('Node Count (N)')
axes_a[0].set_title('First-View Reliability: Theory vs Experiment')
plt.tight_layout()
fig_a.savefig(os.path.join(base, 'fig_theory_firstview.png'), bbox_inches='tight')
print("Saved: fig_theory_firstview.png")

# ════════════════════════════════════════════════════════════
# FIGURE B: Theory vs Experiment — Final Reliability
# ════════════════════════════════════════════════════════════

fig_b, axes_b = plt.subplots(len(drs_to_plot), 1, figsize=(16, 4 * len(drs_to_plot)),
                              sharex=True)
if len(drs_to_plot) == 1:
    axes_b = [axes_b]

for idx, dr in enumerate(drs_to_plot):
    ax = axes_b[idx]
    sub = tdf[tdf['DR'] == dr].sort_values('N')
    ax.plot(sub['N'], sub['P_final_exp'] * 100,
            'o-', markersize=4, linewidth=1.5, color='#2196F3',
            label='Experiment (Final)')
    ax.plot(sub['N'], sub['P_final_3views'] * 100,
            's--', markersize=3, linewidth=1.2, color='#FF9800',
            label='Theory (3 views)')
    ax.plot(sub['N'], sub['P_final_5views'] * 100,
            '^:', markersize=3, linewidth=1.0, color='#9C27B0',
            label='Theory (5 views)')
    ax.set_ylabel(f'DR={dr}%\nReliability (%)')
    ax.legend(loc='lower right', fontsize=8)
    ax.grid(True, alpha=0.3)
    ax.set_ylim(-5, 110)

axes_b[-1].set_xlabel('Node Count (N)')
axes_b[0].set_title('Final Reliability: Theory vs Experiment')
plt.tight_layout()
fig_b.savefig(os.path.join(base, 'fig_theory_final.png'), bbox_inches='tight')
print("Saved: fig_theory_final.png")

# ════════════════════════════════════════════════════════════
# FIGURE C: Oscillation mechanism — decompose into components
# ════════════════════════════════════════════════════════════

fig_c, (ax_c1, ax_c2, ax_c3) = plt.subplots(3, 1, figsize=(16, 14), sharex=True)

ns_range = list(range(16, 101))
dr_example = 95

# Compute all components
data_c = []
for N in ns_range:
    K, groups, f, q_global = compute_global_params(N)
    p_eff = (dr_example / 100.0) ** 2
    
    local_probs = []
    for g in groups:
        local_probs.append(P_group_pass(g, p_eff))
    
    min_g = min(groups)
    max_g = max(groups)
    q_local_min = compute_local_threshold(min_g)
    q_local_max = compute_local_threshold(max_g)
    
    data_c.append({
        'N': N, 'K': K, 'f': f, 'q_global': q_global,
        'min_g': min_g, 'max_g': max_g,
        'q_local_min': q_local_min, 'q_local_max': q_local_max,
        'P_local_min_g': P_group_pass(min_g, p_eff),
        'P_local_max_g': P_group_pass(max_g, p_eff),
        'P_local_avg': np.mean(local_probs),
        'P_phase': P_single_phase(N, dr_example),
        'P_fv': P_first_view(N, dr_example),
        'ratio_q_over_g_min': q_local_min / max(1, min_g - 1),
        'ratio_q_over_g_max': q_local_max / max(1, max_g - 1),
    })
dc = pd.DataFrame(data_c)

# Panel 1: Group sizes and local quorum
ax_c1.step(dc['N'], dc['min_g'], where='mid', label='Min group size', color='blue', linewidth=1.5)
ax_c1.step(dc['N'], dc['max_g'], where='mid', label='Max group size', color='blue', linewidth=1.5, linestyle='--')
ax_c1r = ax_c1.twinx()
ax_c1r.step(dc['N'], dc['q_local_min'], where='mid', label='q_local (min g)', color='red', linewidth=1.2)
ax_c1r.step(dc['N'], dc['q_local_max'], where='mid', label='q_local (max g)', color='red', linewidth=1.2, linestyle='--')
ax_c1.set_ylabel('Group Size (g)', color='blue')
ax_c1r.set_ylabel('Local Quorum (q_local)', color='red')
lines1, labels1 = ax_c1.get_legend_handles_labels()
lines2, labels2 = ax_c1r.get_legend_handles_labels()
ax_c1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=8)
ax_c1.set_title(f'Oscillation Mechanism Decomposition (DR={dr_example}%)')
ax_c1.grid(True, alpha=0.3)

# Panel 2: Local pass probability and quorum ratio
ax_c2.plot(dc['N'], dc['P_local_min_g'] * 100, 'b-', linewidth=1.5,
           label='P(local pass) for smallest group')
ax_c2.plot(dc['N'], dc['P_local_avg'] * 100, 'g-', linewidth=1.5,
           label='P(local pass) average')
ax_c2r = ax_c2.twinx()
ax_c2r.plot(dc['N'], dc['ratio_q_over_g_min'], 'r--', linewidth=1.2,
            label='q_local / (g-1) ratio (smallest group)')
ax_c2.set_ylabel('Local Pass Probability (%)', color='blue')
ax_c2r.set_ylabel('Quorum Difficulty Ratio', color='red')
lines1, labels1 = ax_c2.get_legend_handles_labels()
lines2, labels2 = ax_c2r.get_legend_handles_labels()
ax_c2.legend(lines1 + lines2, labels1 + labels2, loc='lower left', fontsize=8)
ax_c2.grid(True, alpha=0.3)

# Panel 3: Phase probability and first-view probability
ax_c3.plot(dc['N'], dc['P_phase'] * 100, 'b-', linewidth=1.5,
           label='P(single phase passes)')
ax_c3.plot(dc['N'], dc['P_fv'] * 100, 'g-', linewidth=1.5,
           label='P(first-view) = P(phase)^3')

# Overlay experiment
sub_exp = tdf[(tdf['DR'] == dr_example)].sort_values('N')
if not sub_exp.empty:
    ax_c3.plot(sub_exp['N'], sub_exp['P_first_view_exp'] * 100,
               'ro', markersize=4, alpha=0.6, label='Experiment (First-View)')

ax_c3.set_xlabel('Node Count (N)')
ax_c3.set_ylabel('Probability (%)')
ax_c3.legend(loc='lower right', fontsize=8)
ax_c3.grid(True, alpha=0.3)
ax_c3.set_ylim(-5, 110)

plt.tight_layout()
fig_c.savefig(os.path.join(base, 'fig_oscillation_mechanism.png'), bbox_inches='tight')
print("Saved: fig_oscillation_mechanism.png")

# ════════════════════════════════════════════════════════════
# FIGURE D: Critical threshold surface — 3D-like contour
# ════════════════════════════════════════════════════════════

ns_dense = list(range(16, 101))
drs_dense = list(range(88, 100))

Z_fv = np.zeros((len(drs_dense), len(ns_dense)))
Z_final = np.zeros((len(drs_dense), len(ns_dense)))

for i, dr in enumerate(drs_dense):
    for j, N in enumerate(ns_dense):
        Z_fv[i, j] = P_first_view(N, dr) * 100
        Z_final[i, j] = P_final(N, dr, max_views=3) * 100

fig_d, (ax_d1, ax_d2) = plt.subplots(1, 2, figsize=(18, 6))

im1 = ax_d1.contourf(ns_dense, drs_dense, Z_fv,
                      levels=np.arange(0, 105, 5), cmap='RdYlGn')
ax_d1.set_xlabel('Node Count (N)')
ax_d1.set_ylabel('Delivery Rate (%)')
ax_d1.set_title('Theoretical First-View Reliability (%)')
plt.colorbar(im1, ax=ax_d1, shrink=0.9)

im2 = ax_d2.contourf(ns_dense, drs_dense, Z_final,
                      levels=np.arange(0, 105, 5), cmap='RdYlGn')
ax_d2.set_xlabel('Node Count (N)')
ax_d2.set_ylabel('Delivery Rate (%)')
ax_d2.set_title('Theoretical Final Reliability (3 views) (%)')
plt.colorbar(im2, ax=ax_d2, shrink=0.9)

plt.tight_layout()
fig_d.savefig(os.path.join(base, 'fig_theory_contour.png'), bbox_inches='tight')
print("Saved: fig_theory_contour.png")


# ════════════════════════════════════════════════════════════
# Print summary formula
# ════════════════════════════════════════════════════════════

print("""
═══════════════════════════════════════════════════════════════
       MATHEMATICAL MODEL: Double-Layer HotStuff Reliability
═══════════════════════════════════════════════════════════════

INPUT PARAMETERS:
  p  = message delivery rate (0 < p <= 1)
  N  = total number of nodes

DERIVED DISCRETE PARAMETERS:
  K  = round(√N)                          ... branch count
  f  = ⌊(N-1)/3⌋                         ... max Byzantine faults
  q_global = 2f + 1                       ... global quorum threshold

  For group j (j = 0..K-1):
    g_j = ⌊N/K⌋ + 1  if j < (N mod K)    ... group size (fair partition)
    g_j = ⌊N/K⌋      otherwise
    f_local_j = ⌊(g_j - 1)/3⌋            ... local fault tolerance
    q_local_j = 2·f_local_j + 1           ... local quorum threshold

EFFECTIVE DELIVERY PROBABILITY:
  p_eff = p²                              ... each vote needs 2 delivery checks

LOCAL QUORUM (per group, per phase):
  P_local_j = P(Binomial(g_j - 1, p_eff) ≥ q_local_j)
            = 1 - CDF_Binom(q_local_j - 1; g_j - 1, p²)

  If local quorum met: group contributes weight W_j = #successful_votes
  If not met: W_j = 0
  (Group Leader also votes directly with prob p_eff, adding weight 1 if succeeded)

SINGLE PHASE SUCCESS:
  P_phase = P(∑_j W_j ≥ q_global)
  
  Computed via convolution of per-group weight PMFs.

FIRST-VIEW RELIABILITY:
  P_first_view = P_phase³
  
  (HotStuff requires 3 consecutive voting phases: prepare, pre-commit, commit)

FINAL RELIABILITY (with View Change):
  P_final = 1 - (1 - P_first_view)^V
  
  Where V = number of view changes possible within timeout window.

═══════════════════════════════════════════════════════════════

WHY THE OSCILLATION OCCURS:
═══════════════════════════════════════════════════════════════

The oscillation is caused by the interaction of THREE floor/round functions:

  1. K = round(√N)  — jumps at N ∈ {20, 26, 32, 42, 56, 72, 90, ...}
     When K increases by 1, group sizes DROP suddenly:
       N=24: K=5, g=4.8  →  N=25: K=5, g=5.0  (smooth)
       N=25: K=5, g=5.0  →  N=26: K=5, g=5.2  (smooth)
     vs. 
       N=31: K=6, g=5.2  →  N=32: K=6, g=5.3  (smooth)
       but at the K=5→6 transition: g drops from ~6.2 to ~5.3

  2. f_local = ⌊(g-1)/3⌋  — jumps at g ∈ {4, 7, 10, 13, ...}
     When g drops from 7 to 6: f_local stays at 2, q_local stays at 5
     When g drops from 4 to 3: f_local drops from 1 to 0, q_local from 3 to 1
     → Small groups are MUCH easier to satisfy

  3. q_global = 2·⌊(N-1)/3⌋ + 1  — increases steadily with N
     More nodes → more total votes needed globally
     But if groups became smaller (due to K jump), fewer votes per group
     → q_global increases while per-group capacity decreases

The OSCILLATION CYCLE:
  ┌─ K jumps → g drops → P_local drops → reliability DROPS ─┐
  │                                                          │
  └── N grows → g recovers → P_local rises → reliability RISES ──┘

Each "wave" of the oscillation corresponds to one K-plateau.
Within each plateau, reliability generally INCREASES as g grows.
At each K transition, reliability DROPS as g shrinks.

The amplitude of oscillation depends on p:
  - p close to 1: P_local ≈ 1 even for small g → small oscillation
  - p close to 0.9: P_local very sensitive to g → large oscillation
═══════════════════════════════════════════════════════════════
""")
