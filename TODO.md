# TODO

Tracked improvements for the Double-Layer HotStuff project.
Status: `[ ]` open · `[x]` done · `[-]` deferred

---

## Code Quality

- [x] Fix PBFT → HotStuff naming throughout codebase
- [x] Delete dead component `PBFTTable.vue`
- [x] Translate comments to English: `consensus_engine.py`
- [x] Translate comments to English: `consensus_service.py`
- [x] Translate comments to English: `main.py`
- [x] Translate comments to English: `socket_handlers.py`
- [x] Translate comments to English: `robot_agent.py`
- [ ] Translate comments to English: `database.py`, `state.py`, `topology_manager.py`
- [ ] Replace magic numbers in `finalize_consensus_state` with named constants or formula comments (e.g. `8*(n-1)`)
- [ ] Improve silent exception handling in socket event handlers (add logging instead of bare `pass`)

## Project Structure

- [x] Archive historical changelog docs to `docs/history/`
- [x] Organise thesis files into `thesis/` folder
- [x] Remove obsolete one-off test scripts from root
- [x] Move analysis/experiment scripts into `scripts/` directory
- [ ] Pin dependency versions in `backend/requirements.txt`

## Thesis / Report

- [x] Write full BEng FYP LaTeX report (`thesis/main.tex`)
- [x] Create bibliography (`thesis/mylit.bib`)
- [ ] Compile to PDF (upload `thesis/` to Overleaf, or install MiKTeX locally)

## Features / Research

- [ ] Expose `max_round_wait_seconds` as a simulation request parameter (currently hard-coded 3.0 s; too short for large N)
- [ ] Add a `/api/sessions/{id}/reset` endpoint for restarting a round without deleting the session
- [-] Frontend Vue component comment translation (low priority; higher change risk)

## Algorithm Improvements — Grouping Strategy

Root cause of oscillatory reliability: `K = round(√N)` is a discrete staircase function.
Each jump in K causes a sawtooth in group size `g = N/K`, and the BFT quorum
`q_local = 2·⌊(g−1)/3⌋+1` peaks (hardest) whenever `g ≡ 1 (mod 3)` (i.e. g = 4, 7, 10, 13 …),
producing reliability valleys as N grows — the "Three Gears" mechanism.

- [ ] **Direction 1 — Fixed g_target**: replace `K = round(√N)` with `K = round(N / g_target)`
  where `g_target ∈ {6, 9}` (multiples of 3 ⇒ never hit g≡1 mod 3 worst case).
  Simple one-line change; eliminates most of the oscillation.

- [ ] **Direction 2 — Adaptive K**: scan candidate K values and select the one that
  minimises the quorum-difficulty ratio `q_local / g`:
  ```python
  def choose_K(N):
      best_K, best_ratio = 4, 1.0
      for K in range(4, int(N**0.5) * 2):
          g = N / K
          if g < 3: break
          f_local = int((g - 1) // 3)
          q_local = 2 * f_local + 1
          ratio = q_local / g
          if ratio < best_ratio:
              best_ratio = ratio
              best_K = K
      return best_K
  ```
  Most robust option; always picks the locally easiest quorum configuration.

- [ ] **Direction 3 — Align g away from 3m+1**: after computing `K = round(√N)`, nudge K
  up or down by 1 if `round(N/K) % 3 == 1`, to avoid the worst-case quorum ratio
  without changing the overall √N scaling strategy.
