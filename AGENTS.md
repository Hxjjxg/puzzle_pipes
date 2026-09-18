# Repository Guidelines

## Project Structure & Module Organization

- Root Python entry points are `get_puzzle.py` (fetch/store; supports Wrap/torus sizes), `solver.py` (R1–R9 propagation + optional DFS/backtracking, normal and wrap boards), `gui.py` (step replay), and `game.py` (Tkinter game). `test_wrap.py` holds the wrap regression test.
- `puzzles/` contains downloaded `.txt` fixtures; retain useful fixtures for reproducing issues.
- `extension/` contains the Chrome Manifest V3 port (`solver.js`, `content.js`, `content.css`). `README.md` covers formats and behavior; `NOTE-search.md` tracks future search-solver work.

## Build, Test, and Development Commands

The project uses Python’s standard library (including Tkinter); there is no build step or lockfile.

```powershell
python get_puzzle.py                 # Fetch a random 10x10 puzzle
python get_puzzle.py 5 6180259        # Fetch by size and puzzle ID
python get_puzzle.py wrap 10          # Fetch a 10x10 Wrap (torus) puzzle
python solver.py [puzzles\file.txt]  # Run explainable rule propagation
python solver.py --search [file.txt] # Rule propagation, then DFS + backtracking
python test_wrap.py                  # Wrap geometry/R9/tree regression (needs fixtures)
python gui.py --selftest              # Render/replay and interaction smoke test
python game.py --selftest             # Check board logic and reset/rotation flow
python gui.py                          # Open the replay GUI
python game.py                         # Open the playable game
```

Network commands require `puzzle-pipes.com`; use an existing fixture offline.

## Coding Style & Naming Conventions

Use UTF-8, four spaces (no tabs), and readable PEP 8-style Python. Functions/variables use `snake_case`, classes `PascalCase`, and constants `UPPER_SNAKE_CASE`; keep coordinates as `x, y`. Preserve `R1`–`R8` labels and step logging for GUI compatibility. Extension JavaScript uses four spaces and `camelCase`. Update docstrings when behavior or mask semantics change.

## Testing Guidelines

There is no separate suite or coverage threshold. Run `python gui.py --selftest` and `python game.py --selftest` for UI/board changes, and run `python solver.py` on a fixture for solver changes. Add a regression test or fixture for puzzle-specific bugs; use names such as `test_<behavior>` for new Python tests.

## Commit & Pull Request Guidelines

Recent commits use short, imperative Chinese summaries with optional scope (for example, `扩展：...` or `题号支持：...`). Keep commits focused and explain rule/data-format changes in the body. Pull requests should describe behavior and algorithm changes, list commands (including self-tests), link issues, and include screenshots or a recording for GUI/extension changes. Mention new or regenerated fixtures.

## Security & Configuration Tips

Do not commit credentials, browser profiles, or unrelated downloads. `get_puzzle.py` fetches over the network and has a local proxy constant; review URL/proxy changes carefully. Load the unpacked extension in a development Chrome profile and keep its host match limited to `puzzle-pipes.com`.
