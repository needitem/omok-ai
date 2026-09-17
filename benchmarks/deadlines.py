"""Larger synthetic deadline/board-integrity check, not a strength benchmark.

python3 benchmarks/deadlines.py --output benchmarks/deadlines.json
"""
import argparse
import hashlib
import json
import math
import platform
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import omok_ai as ai


def position(index):
    rng = random.Random(9000 + index)
    count = (2, 12, 32, 60, 100)[index % 5]
    board = ai.empty_board()
    for ply in range(count):
        player = 1 + ply % 2
        candidates = sorted(ai._candidates(board))
        rng.shuffle(candidates)
        for r, c in candidates:
            if ai.is_forbidden(board, r, c, player, "renju"):
                continue
            board[r][c] = player
            if not ai.is_win(board, r, c, player, "renju"):
                break
            board[r][c] = 0
        else:
            raise RuntimeError("Could not construct a legal nonterminal position")
    return board


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--positions", type=int, default=100)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--budget", type=float, default=.05)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = {
        "platform": platform.platform(), "python": sys.version,
        "engine_sha256": hashlib.sha256((ROOT / "omok_ai.py").read_bytes()).hexdigest(),
        "positions": args.positions, "repeats": args.repeats, "budget_s": args.budget,
        "position_seeds": "9000 + index; see position() for generation",
        "rule": "renju", "forbid_config": ai.FORBID_CFG,
        "cache_policy": "Shared process; cache retained between calls.",
        "measurements": {},
    }
    functions = (ai.search_move, ai.prove_win_move_ex)
    for fn in functions:
        report["measurements"][fn.__name__] = {"samples_s": [], "statuses": {}}
    for index in range(args.positions):
        original = position(index)
        for fn in functions:
            entry = report["measurements"][fn.__name__]
            for _ in range(args.repeats):
                board = [row[:] for row in original]
                start = time.perf_counter()
                result = fn(board, 1, "renju", time_budget=args.budget)
                entry["samples_s"].append(time.perf_counter() - start)
                assert board == original, (index, fn.__name__, "board changed")
                if result and result.get("move"):
                    r, c = result["move"]
                    assert board[r][c] == 0 and not ai.is_forbidden(board, r, c, 1, "renju")
                status = (result.get("status", "TIMEOUT" if result.get("timed_out") else "RETURNED")
                          if result else "NONE")
                entry["statuses"][status] = entry["statuses"].get(status, 0) + 1
        if (index + 1) % 20 == 0:
            print(f"Validated {index + 1}/{args.positions} positions", flush=True)
    for name, entry in report["measurements"].items():
        ordered = sorted(entry["samples_s"])
        entry["p50_s"] = ordered[math.ceil(len(ordered) * .5) - 1]
        entry["p95_s"] = ordered[math.ceil(len(ordered) * .95) - 1]
        entry["max_s"] = ordered[-1]
        entry["over_tolerance_count"] = sum(
            sample > args.budget + max(.01, args.budget * .1) for sample in ordered)
        print(name, {key: value for key, value in entry.items() if key != "samples_s"})
    report["board_and_legality_checks"] = "passed for every call"
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
