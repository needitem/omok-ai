# omok-ai

A Gomoku / Renju (오목) move engine in pure Python, paired with the
tournament-strength [Rapfi](https://github.com/dhbloo/rapfi) NNUE engine.

The Python layer contributes configurable **rule enforcement and tactical
search**:

- **Forbidden-move (금수) detection** for both colors — double-three (3·3),
  double-four (4·4), and overline (장목) — configurable per color and per rule
  (`renju` / `korean` / `standard` / `freestyle`).
- **Proven wins**: a VCF/VCT-style prover (`prove_win_move`) under the configured
  rule implementation, independent of the search engine. Nested false-three
  cases use an approximation; this is not a complete official Renju ruleset.
- **Immediate win / must-block** tactics computed deterministically.

Rapfi provides the general search. Callers combining the two should validate
its output with the Python rules and prefer proven tactics when available;
the standalone Rapfi wrapper does not perform that filtering automatically.

## Layout

```
omok_ai.py       # pure-Python engine: rules, forbidden moves, prover, scoring
rapfi_bot.py     # arm's-length subprocess wrapper for the Rapfi binary
build_omok.py    # optional: compile omok_ai.py to a C extension via Cython
rapfi_engine/    # bundled Rapfi binary + NNUE weights (third-party, see NOTICE.md)
```

`omok_ai.py` has **no dependencies** (Python 3 standard library only).

## Platform note

The bundled `rapfi_engine/pbrain-rapfi` is a **Linux / ARM aarch64** build.
It will not run on x86-64 or macOS (including Apple Silicon). For other platforms, build Rapfi from
[upstream](https://github.com/dhbloo/rapfi) and replace the binary (keep the
`.lz4` weights, which are architecture-independent). The pure-Python
`omok_ai.py` runs anywhere.

## Usage

Boards are `15x15` lists of ints: `0` empty, `1` black, `2` white.

### Rule enforcement (pure Python, no Rapfi needed)

```python
import omok_ai

b = omok_ai.empty_board()          # 15x15 of zeros
b[7][7] = omok_ai.BLACK            # 1 = black, 2 = white

# Is (r, c) a forbidden move for this color under this rule?
omok_ai.is_forbidden(b, 7, 8, omok_ai.BLACK, "renju")   # -> bool

# Forced-win prover: returns {'move': (r, c), ...} or None
omok_ai.prove_win_move(b, omok_ai.BLACK, "renju", time_budget=1.5)
```

For `renju` / `korean`, the Python default preserves the original app's rule:
**both colors** forbid double-three, double-four and overline. To allow white
to play without those restrictions, configure it explicitly:

```python
omok_ai.set_forbid(white={
    "three_three": False, "four_four": False, "overline": False,
})
```

`set_forbid` is process-wide configuration; set it before starting searches,
and do not change it concurrently with an active search. Python's `standard`
and `freestyle` both allow five or more stones, without forbidden moves. Their
semantics are not guaranteed to match every Rapfi rule mode.

### Timed Python search

```python
result = omok_ai.search_move(b, omok_ai.BLACK, time_budget=0.05)
# result: move, score, reason, depth, timed_out, elapsed_ms; or None
proof = omok_ai.prove_win_move_ex(b, omok_ai.BLACK, time_budget=0.05)
# proof['status']: 'PROVEN_WIN', 'NO_PROOF', or 'TIMEOUT'
```

Search checks a shared monotonic deadline throughout candidate evaluation and
recursive search, restoring temporary stones on interruption. `depth` is the
last fully completed iteration; if none completed, a validated legal candidate
is returned with depth 0. Zero/negative budgets, or expiration before any legal
candidate is validated, return `None`. Checks are cooperative, so OS scheduling
and one small in-progress operation can still cause slight deadline overshoot.

`prove_win_move` retains its original move-or-`None` API. Use the `_ex` version
to distinguish timeout from a completed search without a proof. Neither
`NO_PROOF` nor `None` establishes that a position is safe. Attacking candidate
and depth limits can miss wins; non-forcing proof branches enumerate every
legal defensive square. A proven opponent attack point is not automatically
a proven defensive move for the other player.

### Best move via Rapfi

```python
import rapfi_bot

board = [[0]*15 for _ in range(15)]
for c in (3, 4, 5, 6):
    board[7][c] = 1               # black four in a row

rapfi_bot.available()             # -> True if the engine binary is present
rapfi_bot.best_move(board, me=1, rule="korean", timeout_ms=400)
# -> (row, col)  e.g. (7, 7) or (7, 2) to complete the five

rapfi_bot.best_move_ex(board, 1, "korean", 400)
# -> {'move': (r, c), 'pv': [(r, c), ...], 'eval': '...'}
```

For the Rapfi wrapper, `rule` is one of `"korean"`, `"renju"` (both map to Rapfi rule 2),
`"standard"`, `"freestyle"`.

### Combining both (recommended pattern)

Prefer a proven win / forced defense from `omok_ai`, otherwise take Rapfi's move
but reject it if it is forbidden or loses to a proven counter. See the
docstrings in `omok_ai.py` (`_gain_points`, `prove_win_move`, `place_score`,
`_ordered`) for the building blocks.

## Optional: compile for speed

`omok_ai.py` can be compiled to a C extension without any source changes:

```bash
pip install cython
python3 build_omok.py build_ext --inplace
```

The resulting `omok_ai.*.so` shadows the `.py` on import — same logic, faster.

## Validation and benchmarks

```bash
python3 -m unittest discover -s tests -v
python3 omok_ai.py
python3 benchmarks/baseline.py --output benchmarks/after.json
python3 benchmarks/deadlines.py --output benchmarks/deadlines.json
```

See [the implementation results](PERFORMANCE_RESULTS.md) for measured changes,
remaining limitations and the original baseline.

## Licensing

- First-party code (`omok_ai.py`, `rapfi_bot.py`, `build_omok.py`): **MIT** — see `LICENSE`.
- Bundled engine assets under `rapfi_engine/`: third-party — the `pbrain-rapfi`
  binary is **GPL-3.0**, the NNUE weights are **CC0-1.0**. See
  [`rapfi_engine/NOTICE.md`](rapfi_engine/NOTICE.md).
