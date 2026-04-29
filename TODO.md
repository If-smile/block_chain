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
- [ ] Move test scripts into a `tests/` directory
- [ ] Pin dependency versions in `backend/requirements.txt`

## Thesis / Report

- [x] Write full BEng FYP LaTeX report (`thesis/main.tex`)
- [x] Create bibliography (`thesis/mylit.bib`)
- [ ] Compile to PDF (upload `thesis/` to Overleaf, or install MiKTeX locally)

## Features / Research

- [ ] Expose `max_round_wait_seconds` as a simulation request parameter (currently hard-coded 3.0 s; too short for large N)
- [ ] Add a `/api/sessions/{id}/reset` endpoint for restarting a round without deleting the session
- [-] Frontend Vue component comment translation (low priority; higher change risk)
