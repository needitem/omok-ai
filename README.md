# omok-ai

A Gomoku / Renju (오목) move engine in pure Python, paired with the
tournament-strength [Rapfi](https://github.com/dhbloo/rapfi) NNUE engine.

The Python layer contributes exact **rule enforcement and tactical
guarantees** that a raw search engine can miss:

- **Forbidden-move (금수) detection** for both colors — double-three (3·3),
  double-four (4·4), and overline (장목) — configurable per color and per rule
  (`renju` / `korean` / `standard` / `freestyle`).
- **Proven wins**: a VCF/VCT-style prover (`prove_win_move`) that hard-guarantees
  a forced win when one is provable, independent of the search engine.
- **Immediate win / must-block** tactics computed deterministically.

Rapfi provides the strong general search; the Python layer filters its output
for legality (e.g. Rapfi treats only black as forbidden-bound) and overrides it
with proven tactics when available.

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
It will not run on x86-64. For other platforms, build Rapfi from
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

`rule` is one of `"korean"`, `"renju"` (both = black-forbidden ≈ standard renju),
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

## Licensing

- First-party code (`omok_ai.py`, `rapfi_bot.py`, `build_omok.py`): **MIT** — see `LICENSE`.
- Bundled engine assets under `rapfi_engine/`: third-party — the `pbrain-rapfi`
  binary is **GPL-3.0**, the NNUE weights are **CC0-1.0**. See
  [`rapfi_engine/NOTICE.md`](rapfi_engine/NOTICE.md).
