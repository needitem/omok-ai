import copy
import itertools
import random
import time
import unittest
from unittest.mock import patch

import omok_ai as ai


def legacy_open_three(b, r, c, dr, dc, p):
    """Original trial-placement algorithm, retained as a differential oracle."""
    if ai._run_through(ai._states(b, r, c, dr, dc, p), 5) >= 4:
        return False
    for k in range(-4, 5):
        rr, cc = r + dr * k, c + dc * k
        if ai._in(b, rr, cc) and b[rr][cc] == 0:
            b[rr][cc] = p
            try:
                if (ai._open_four_through(b, r, c, dr, dc, p)
                        or ai._open_four_through(b, rr, cc, dr, dc, p)):
                    return True
            finally:
                b[rr][cc] = 0
    return False


def tactical_board():
    b = ai.empty_board()
    for c in (3, 4, 5):
        b[7][c] = ai.BLACK
    for c in (3, 4, 5, 6):
        b[10][c] = ai.WHITE
    b[10][2] = ai.BLACK
    return b


class RulesTests(unittest.TestCase):
    def tearDown(self):
        ai.set_forbid(black=ai._DEFAULT_FORBID, white=ai._DEFAULT_FORBID)

    def test_line_patterns_against_trial_placement(self):
        # Exhaust every interior seven-cell pattern for both colors; random
        # full boards add long lines, edges, diagonals and distant stones.
        for color in (ai.BLACK, ai.WHITE):
            for pattern in itertools.product((0, 1, 2), repeat=6):
                b = ai.empty_board()
                for c, value in zip((4, 5, 6, 8, 9, 10), pattern):
                    b[7][c] = value
                b[7][7] = color
                self.assertEqual(ai._open_three_in_dir(b, 7, 7, 0, 1, color),
                                 legacy_open_three(b, 7, 7, 0, 1, color))
        rng = random.Random(4827)
        for _ in range(1500):
            b = [[rng.choice((0, 0, 1, 2)) for _ in range(15)] for _ in range(15)]
            r, c, color = rng.randrange(15), rng.randrange(15), rng.choice((1, 2))
            b[r][c] = color
            original = copy.deepcopy(b)
            for dr, dc in ai.DIRS:
                self.assertEqual(ai._open_three_in_dir(b, r, c, dr, dc, color),
                                 legacy_open_three(b, r, c, dr, dc, color))
                self.assertEqual(ai._line_run(b, r, c, dr, dc, color),
                                 ai._run_through(ai._states(b, r, c, dr, dc, color), 5))
            self.assertEqual(b, original)

    def test_forbidden_patterns_match_original_across_configs(self):
        rng = random.Random(813)
        for toggles in itertools.product((False, True), repeat=3):
            cfg = dict(zip(("three_three", "four_four", "overline"), toggles))
            ai.set_forbid(black=cfg, white=cfg)
            for _ in range(30):
                b = [[rng.choice((0, 0, 0, 1, 2)) for _ in range(15)] for _ in range(15)]
                r, c = rng.randrange(15), rng.randrange(15)
                b[r][c] = 0
                original = copy.deepcopy(b)
                for color in (1, 2):
                    actual = ai.is_forbidden(b, r, c, color, "renju")
                    with patch.object(ai, "_open_three_in_dir", legacy_open_three):
                        expected = ai.is_forbidden(b, r, c, color, "renju")
                    self.assertEqual(actual, expected)
                self.assertEqual(b, original)

    def test_default_white_rules_are_preserved(self):
        b = ai.empty_board()
        for c in range(2, 7):
            b[7][c] = ai.WHITE
        self.assertTrue(ai.is_forbidden(b, 7, 7, ai.WHITE, "renju"))
        ai.set_forbid(white={"overline": False})
        self.assertFalse(ai.is_forbidden(b, 7, 7, ai.WHITE, "renju"))
        with ai._placed(b, 7, 7, ai.WHITE):
            self.assertTrue(ai.is_win(b, 7, 7, ai.WHITE, "renju"))


class SearchTests(unittest.TestCase):
    def test_defense_before_false_vcf_for_both_colors(self):
        for color in (1, 2):
            b = tactical_board()
            if color == 2:
                b = [[3 - v if v else 0 for v in row] for row in b]
            original = copy.deepcopy(b)
            result = ai.search_move(b, color, time_budget=.1)
            self.assertEqual(result["move"], (10, 7))
            self.assertNotEqual(result.get("proof_status"), "PROVEN_WIN")
            self.assertEqual(b, original)

    def test_vcf_and_vct_reject_opponent_immediate_win(self):
        for fn in (ai._vcf, ai._vct):
            b = tactical_board()
            original = copy.deepcopy(b)
            self.assertIsNone(fn(b, 1, "renju", 2, time.perf_counter() + 3))
            self.assertEqual(b, original)

    def test_actual_immediate_and_forced_wins_survive(self):
        b = ai.empty_board()
        for c in (3, 4, 5):
            b[7][c] = ai.BLACK
        for fn in (ai._vcf, ai._vct):
            result = fn(b, 1, "renju", 2, time.perf_counter() + 3)
            self.assertIn(result, ((7, 2), (7, 6)))
        b[7][6] = ai.BLACK
        b[10][3:7] = [ai.WHITE] * 4
        result = ai.search_move(b, 1, time_budget=.1)
        self.assertIn(result["move"], ((7, 2), (7, 7)))
        self.assertEqual(result["proof_status"], "PROVEN_WIN")

    def test_no_proof_and_timeout_are_distinct(self):
        b = ai.empty_board()
        self.assertEqual(ai.prove_win_move_ex(b, 1, time_budget=0)["status"], "TIMEOUT")
        self.assertEqual(ai.prove_win_move_ex(b, 1, time_budget=.2)["status"], "NO_PROOF")
        self.assertIsNone(ai.prove_win_move(b, 1, time_budget=0))
        self.assertIsNone(ai.search_move(b, 1, time_budget=0))

    def test_timeout_does_not_evaluate_position(self):
        b = ai.empty_board()
        with patch.object(ai, "_evaluate", side_effect=AssertionError("evaluation after timeout")):
            with self.assertRaises(ai._SearchTimeout):
                ai._negamax(b, 1, "renju", 0, -ai.INF, ai.INF, 0)

    def test_incomplete_iteration_keeps_previous_result(self):
        b = ai.empty_board()
        b[7][7], b[7][8] = 1, 2
        with patch.object(ai, "_proof_stage", return_value=("TIMEOUT", None)), \
                patch.object(ai, "_root_search", side_effect=[
                    {"move": (6, 6), "score": 123}, ai._SearchTimeout()]):
            result = ai.search_move(b, 1, time_budget=1)
        self.assertEqual(result["move"], (6, 6))
        self.assertEqual(result["depth"], 1)
        self.assertEqual(result["score"], 123)
        self.assertTrue(result["timed_out"])
        self.assertNotIn("저지", result["reason"])

    def test_nested_forced_reply_restored_on_timeout(self):
        b = ai.empty_board()
        b[7][3:6] = [1, 1, 1]
        b[7][2] = 2
        original = copy.deepcopy(b)
        fn = ai._vcf
        # First call enters the real VCF; its recursive child interrupts while
        # both the attacking and mandatory defensive stone are on the board.
        def recurse(*args):
            self.assertNotEqual(args[0], original)
            raise ai._SearchTimeout
        with patch.object(ai, "_vcf", side_effect=recurse):
            with self.assertRaises(ai._SearchTimeout):
                fn(b, 1, "renju", 4, time.perf_counter() + 3)
        self.assertEqual(b, original)

    def test_nested_moves_restored_on_unexpected_exception(self):
        b = ai.empty_board()
        b[7][7] = 1
        original = copy.deepcopy(b)
        with patch.object(ai, "_negamax", side_effect=RuntimeError("injected")):
            with self.assertRaises(RuntimeError):
                ai._root_search(b, 2, 1, "renju", [(7, 8)], 2, time.perf_counter() + 1)
        self.assertEqual(b, original)

    def test_vct_forced_reply_restored_on_timeout(self):
        b = ai.empty_board()
        b[7][3:6] = [1, 1, 1]
        b[7][2] = 2
        original = copy.deepcopy(b)
        fn = ai._vct
        with patch.object(ai, "_threat_moves_vct", return_value=[(7, 6)]), \
                patch.object(ai, "_vct", side_effect=ai._SearchTimeout):
            with self.assertRaises(ai._SearchTimeout):
                fn(b, 1, "renju", 4, time.perf_counter() + 3)
        self.assertEqual(b, original)

    def test_fork_preserves_already_placed_stone_on_timeout(self):
        b = ai.empty_board()
        b[7][7] = 1
        original = copy.deepcopy(b)
        with patch.object(ai, "_winning_followups", side_effect=ai._SearchTimeout):
            with self.assertRaises(ai._SearchTimeout):
                ai._fork_unstoppable(b, 1, 2, 7, 7, "renju", time.perf_counter() + 1)
        self.assertEqual(b, original)

    def test_proof_defenses_include_distant_points(self):
        b = ai.empty_board()
        b[7][7] = 1
        defenses = set(ai._legal_defenses(b, 2, "renju", time.perf_counter() + 1))
        self.assertEqual(len(defenses), 224)
        self.assertIn((0, 0), defenses)
        self.assertIn((14, 14), defenses)

    def test_deadline_and_board_integrity_smoke(self):
        rng = random.Random(36)
        for count in (2, 12, 32, 80):
            b = ai.empty_board()
            for i, index in enumerate(rng.sample(range(225), count)):
                b[index // 15][index % 15] = 1 + i % 2
            original = copy.deepcopy(b)
            for fn in (ai.search_move, ai.prove_win_move_ex):
                start = time.perf_counter()
                result = fn(b, 1, time_budget=.02)
                # A generous CI guard; detailed p95 timing belongs in the
                # benchmark, not a scheduler-sensitive 1ms assertion.
                self.assertLess(time.perf_counter() - start, .15)
                self.assertEqual(b, original)
                if result and result.get("move"):
                    r, c = result["move"]
                    self.assertEqual(b[r][c], 0)
                    self.assertFalse(ai.is_forbidden(b, r, c, 1, "renju"))

    def test_invalid_budgets_rejected(self):
        for budget in (float("nan"), float("inf")):
            for fn in (ai.search_move, ai.prove_win_move_ex):
                with self.assertRaises(ValueError):
                    fn(ai.empty_board(), 1, time_budget=budget)


if __name__ == "__main__":
    unittest.main()
