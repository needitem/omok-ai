"""Reproducible, dependency-free baseline; does not modify engine code.

python3 benchmarks/baseline.py --output benchmarks/baseline.json
python3 benchmarks/baseline.py --profile > benchmarks/profile.txt
"""
import argparse
import cProfile
import hashlib
import json
import platform
import pstats
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import omok_ai as ai


def fixtures():
    result = {"opening_2": ai.empty_board()}
    result["opening_2"][7][7] = ai.BLACK
    result["opening_2"][7][8] = ai.WHITE
    for count in (12, 32):
        rng = random.Random(1700 + count)
        board = ai.empty_board()
        for ply in range(count):
            player = ai.BLACK if ply % 2 == 0 else ai.WHITE
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
                raise RuntimeError("Could not construct nonterminal fixture")
        result[f"seeded_{count}"] = board
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--profile", action="store_true")
    args = parser.parse_args()
    boards = fixtures()
    if args.profile:
        profiler = cProfile.Profile()
        profiler.runcall(ai.search_move, boards["seeded_32"], ai.BLACK,
                        "renju", time_budget=0.05)
        pstats.Stats(profiler).strip_dirs().sort_stats("cumulative").print_stats(25)
        return
    report = {
        "revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "engine_sha256": hashlib.sha256((ROOT / "omok_ai.py").read_bytes()).hexdigest(),
        "cache_policy": "One process; pattern cache retained between calls, first sample included.",
        "python": sys.version,
        "platform": platform.platform(),
        "rules": {"rule": "renju", "forbid_config": ai.FORBID_CFG},
        "note": "Synthetic positions, default config; not a strength or p95 benchmark.",
        "fixtures": boards,
        "measurements": [],
    }
    for name, original in boards.items():
        for method in ("best_move", "search_move", "prove_win_move"):
            for budget in ([None] if method == "best_move" else [0.05, 0.5]):
                samples, outputs, unchanged = [], [], []
                for _ in range(args.repeats):
                    board = [row[:] for row in original]
                    kwargs = {} if budget is None else {"time_budget": budget}
                    start = time.perf_counter()
                    output = getattr(ai, method)(board, ai.BLACK, "renju", **kwargs)
                    samples.append(time.perf_counter() - start)
                    outputs.append(output)
                    unchanged.append(board == original)
                item = {
                    "fixture": name, "method": method, "budget_s": budget,
                    "samples_s": samples, "median_s": statistics.median(samples),
                    "max_s": max(samples), "board_unchanged": all(unchanged),
                    "outputs": outputs,
                }
                report["measurements"].append(item)
                print(f"{name:12} {method:15} budget={str(budget):4} "
                      f"median={item['median_s']:.4f}s max={item['max_s']:.4f}s "
                      f"unchanged={item['board_unchanged']}", flush=True)
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
