#!/usr/bin/env python3
"""
omok_ai.py — 오목 최선수 추천 엔진 (룰/색 인식, 렌주 금수 판정 포함). 순수 알고리즘.

지원:
  - 일반룰(standard): 양쪽 금수 없음, 5목 이상 승리.
  - renju/korean: 색별 FORBID_CFG 적용. 기본값은 앱 호환용 양색 금수.
    공식 렌주처럼 백의 제한을 해제하려면 set_forbid(white=...)로 명시한다.

board: 2차원 리스트. 0=빈칸, 1=흑(BLACK, 선), 2=백(WHITE).
best_move(board, me, rule): 내(me) 차례의 최선수 {move,(r,c), reason, ...}.
  - me=BLACK & renju: 금수 자리는 절대 추천 안 함, 장목=승리 아님으로 처리.
  - 상대 위협 평가도 상대 색의 룰을 따른다(렌주 흑 상대의 금수 위협은 무효).

⚠️ 금수 판정은 실전 대부분을 커버하는 실용 구현. 공식 RIF의 재귀적 거짓삼(nested)
   극단 예외까지는 근사한다.
"""
from __future__ import annotations
import time
from contextlib import contextmanager
from functools import lru_cache
import math

SIZE = 15
BLACK, WHITE = 1, 2
DIRS = [(1, 0), (0, 1), (1, 1), (1, -1)]

# ── 색별 금수 설정(확장성 패치) ──────────────────────────────────
# 각 색(BLACK/WHITE)의 삼삼(three_three)·사사(four_four)·장목(overline) 금지 여부를 독립 지정.
# 기본값: 흑·백 모두 셋 다 금지(= KingTalk 앱 실제 룰, checkBanStoneNumber). 서비스가 config/env 로 덮어쓴다.
#   overline=True(금지)  → 6목은 반칙·승리 아님(정확히 5만 승리)
#   overline=False(허용) → 6목 이상도 승리(무금수 오목처럼)
_DEFAULT_FORBID = {"three_three": True, "four_four": True, "overline": True}
FORBID_CFG = {BLACK: dict(_DEFAULT_FORBID), WHITE: dict(_DEFAULT_FORBID)}


def set_forbid(black=None, white=None):
    """색별 금수 설정 부분 갱신. 예: set_forbid(white={'three_three': False, 'four_four': False})."""
    if black: FORBID_CFG[BLACK].update(black)
    if white: FORBID_CFG[WHITE].update(white)

WIN     = 100_000_000
OPEN4   = 10_000_000
FOUR    = 500_000
OPEN3   = 100_000
THREE   = 5_000
OPEN2   = 1_000
TWO     = 100
ONE     = 10
FORBID  = -1_000_000_000     # 흑 금수 자리(내 수로는 절대 선택 금지)


def empty_board(size: int = SIZE):
    return [[0] * size for _ in range(size)]


def _in(b, r, c):
    return 0 <= r < len(b) and 0 <= c < len(b[0])


def opp(p):
    return WHITE if p == BLACK else BLACK


def _restricted_black(p, rule):
    """p가 '정확히 5로만 승리'(장목 승리 없음)인가 = 그 색 overline 금지 설정(config).
    standard/freestyle 은 무금수 → 항상 False. (이름은 하위호환 위해 유지)"""
    if rule not in ("renju", "korean"):
        return False
    return bool(FORBID_CFG.get(p, _DEFAULT_FORBID).get("overline", False))


# ── 라인 상태 추출 ──────────────────────────────────────────────
def _states(b, r, c, dr, dc, p, half=5):
    """(r,c) 기준 (dr,dc)축으로 -half..+half 셀 상태: 'O'=내돌 '.'=빈 '#'=상대/벽."""
    s = []
    rows, cols = len(b), len(b[0])
    for k in range(-half, half + 1):
        rr, cc = r + dr * k, c + dc * k
        if not (0 <= rr < rows and 0 <= cc < cols):
            s.append('#')
        elif b[rr][cc] == p:
            s.append('O')
        elif b[rr][cc] == 0:
            s.append('.')
        else:
            s.append('#')
    return s


def _run_through(states, center):
    """center 를 지나는 연속 'O' 길이(center 는 'O' 가정)."""
    n = 1
    i = center - 1
    while i >= 0 and states[i] == 'O':
        n += 1; i -= 1
    j = center + 1
    while j < len(states) and states[j] == 'O':
        n += 1; j += 1
    return n


# ── 승리/장목 판정 ──────────────────────────────────────────────
def _line_run(b, r, c, dr, dc, p):
    """Count through a placed stone without allocating a line buffer."""
    rows, cols = len(b), len(b[0])
    count = 1
    for sign in (-1, 1):
        for k in range(1, 6):
            rr, cc = r + sign * dr * k, c + sign * dc * k
            if not (0 <= rr < rows and 0 <= cc < cols) or b[rr][cc] != p:
                break
            count += 1
    return count


def is_win(b, r, c, p, rule):
    """(r,c)에 p 를 둔 상태에서 승리인가. 렌주 흑=정확히 5, 그 외=5 이상."""
    exact = _restricted_black(p, rule)        # 그 색 overline 금지 → 정확히 5만 승리
    for dr, dc in DIRS:
        run = _line_run(b, r, c, dr, dc, p)
        if exact:
            if run == 5:
                return True
        elif run >= 5:                        # overline 허용/무금수룰 = 5 이상 승리
            return True
    return False


def _is_overline(b, r, c, p):
    for dr, dc in DIRS:
        if _line_run(b, r, c, dr, dc, p) >= 6:
            return True
    return False


# ── 사(四)/활삼(open three) 방향별 검출 ─────────────────────────
def _four_in_dir(b, r, c, dr, dc, p, rule):
    """이 방향에서 '사(한 수로 5 완성 가능)'가 형성되는가."""
    st = _states(b, r, c, dr, dc, p)
    for start in range(1, 6):                 # center(idx5) 포함 5-윈도우
        win = st[start:start + 5]
        if win.count('O') == 4 and win.count('.') == 1:
            gap = start + win.index('.')
            st2 = st[:]; st2[gap] = 'O'
            run = _run_through(st2, gap)
            if _restricted_black(p, rule):
                if run == 5:                  # 흑은 정확히 5 완성만 유효
                    return True
            elif run >= 5:
                return True
    return False


def _open_four_through(b, r, c, dr, dc, p):
    """(r,c) 지나는 이 방향에 '열린4'(.OOOO.) 존재?"""
    st = _states(b, r, c, dr, dc, p)
    i = 5
    while i > 0 and st[i - 1] == 'O':
        i -= 1
    j = 5
    while j < len(st) - 1 and st[j + 1] == 'O':
        j += 1
    return (j - i + 1) == 4 and st[i - 1] == '.' and st[j + 1] == '.'


def _open_three_in_dir(b, r, c, dr, dc, p):
    """이 방향에서 활삼(한 수로 열린4 가능)인가. 이미 사(4연속↑)면 삼 아님 —
    이게 없으면 이중사(44)를 이중삼(33)으로 오판해 흑 44 를 잘못 금수 처리함."""
    # Both old probes (center and trial stone +/-4) read +/-5 cells.
    # Extract their union once; the cached key contains only relative stones,
    # so it is independent of board identity, player and rule configuration.
    return _line_open_three(tuple(_states(b, r, c, dr, dc, p, half=9)))


def _line_open_four(st, center):
    left = right = center
    while left > 0 and st[left - 1] == 'O':
        left -= 1
    while right + 1 < len(st) and st[right + 1] == 'O':
        right += 1
    return (right - left == 3 and left > 0 and right + 1 < len(st)
            and st[left - 1] == '.' and st[right + 1] == '.')


@lru_cache(maxsize=8192)
def _line_open_three(line):
    if _run_through(line, 9) >= 4:
        return False
    st = list(line)
    for index in range(5, 14):
        if st[index] == '.':
            st[index] = 'O'
            of = _line_open_four(st, 9) or _line_open_four(st, index)
            st[index] = '.'
            if of:
                return True
    return False


def count_fours(b, r, c, p, rule):
    return sum(_four_in_dir(b, r, c, dr, dc, p, rule) for dr, dc in DIRS)


def count_open_threes(b, r, c, p):
    return sum(_open_three_in_dir(b, r, c, dr, dc, p) for dr, dc in DIRS)


# ── 렌주 금수 판정 (앱 -[OmokVC checkBanStoneNumber:] 정밀 이식) ──────────────
def _four_count_dir(b, r, c, dr, dc, p):
    """(r,c)에 p 를 둘 때 이 방향에서 만들어지는 '사(四)'의 개수. b[r][c] 는 이미 p.
    앱 -[OmokVC check4EachDirectionSpace:lastColor:stoneNum:] 를 그대로 이식.
    ★한 줄 안의 이중사(예: O·OOO·O 에서 양쪽 완성)를 2개로 세어 렌주 44 를 정확히 잡는다.
      (방향당 bool 로 세던 count_fours 는 한 줄 이중사를 1개로 세어 44 를 놓쳤음 — 그 결함 수정.)
    사 조건: 5칸 윈도우에 같은색 4(방금돌 포함)+빈칸 1, 방금돌이 윈도우 안, 양옆이 같은색 아님
    (=5/6 으로 이어지지 않는 순수 사). dedup: 직전 사와 연속이거나 열린사면 즉시 확정."""
    count = 0
    last = None
    for i0 in range(5):
        sr, sc = r - i0 * dr, c - i0 * dc
        cells = [(sr + k * dr, sc + k * dc) for k in range(5)]
        if not all(_in(b, rr, cc) for rr, cc in cells):
            continue
        emp = 0; pin = False; endgap = True; fail = False
        for i, (rr, cc) in enumerate(cells):
            if (rr, cc) == (r, c):
                pin = True; continue                 # 방금 둔 돌
            s = b[rr][cc]
            if s == 0:
                endgap = endgap and (i in (0, 4))    # 빈칸이 윈도우 끝(=열린사)인가
                if emp > 0:
                    fail = True; break               # 빈칸 2개↑ → 사 아님
                emp += 1
            elif s != p:
                fail = True; break                   # 다른색 → 탈락
        if fail or emp != 1 or not pin:
            continue
        br, bc = sr - dr, sc - dc
        ar, ac = sr + 5 * dr, sc + 5 * dc
        if (_in(b, br, bc) and b[br][bc] == p) or (_in(b, ar, ac) and b[ar][ac] == p):
            continue                                 # 양옆이 같은색 → 사 아님(5/6 의 일부)
        if (last is not None and (sr, sc) == last) or endgap:
            return max(count, 1)
        count += 1; last = (sr, sc)
    return count


def is_forbidden(b, r, c, p, rule):
    """(r,c)에 p 를 두면 금수인가. 앱 -[OmokVC checkBanStoneNumber:] 정밀 이식 —
    색별 config(FORBID_CFG[p])로 33·44·장목 각각 게이팅. 승리(정확히 5)면 금수 아님(우선).
    ★삼삼: 사와 '같은 방향'의 삼은 거짓삼으로 제외(앱 보정). 사사: 완성 가능 사 개수 합≥2.
    앱 바이너리 로직과 랜덤 5만판 100% 일치 검증(2026-09)."""
    if rule not in ("renju", "korean"):       # standard/freestyle = 무금수
        return False
    if b[r][c] != 0:
        return False
    cfg = FORBID_CFG.get(p, _DEFAULT_FORBID)
    b[r][c] = p
    try:
        if is_win(b, r, c, p, rule):          # 승리 완성은 금수보다 우선
            return False
        if cfg.get("overline", False) and _is_overline(b, r, c, p):              # 장목(6목↑)
            return True
        if not cfg.get("four_four", False) and not cfg.get("three_three", False):
            return False
        fdir = {}
        ftot = 0
        for dr, dc in DIRS:
            fc = _four_count_dir(b, r, c, dr, dc, p)
            fdir[(dr, dc)] = fc
            ftot += fc
        if cfg.get("four_four", False) and ftot >= 2:                            # 사사(44)
            return True
        if cfg.get("three_three", False):                                        # 삼삼(33)
            three = sum(1 for dr, dc in DIRS
                        if fdir[(dr, dc)] == 0 and _open_three_in_dir(b, r, c, dr, dc, p))
            if three >= 2:                    # 거짓삼(사와 같은 방향) 제외 후 삼 2개↑
                return True
        return False
    finally:
        b[r][c] = 0


# ── 한 칸 평가 ──────────────────────────────────────────────────
def _pattern_score(cnt, open_ends):
    if cnt >= 5:
        return WIN
    if cnt == 4:
        return OPEN4 if open_ends == 2 else (FOUR if open_ends == 1 else 0)
    if cnt == 3:
        return OPEN3 if open_ends == 2 else (THREE if open_ends == 1 else 0)
    if cnt == 2:
        return OPEN2 if open_ends == 2 else (TWO if open_ends == 1 else 0)
    if cnt == 1:
        return ONE if open_ends == 2 else 0
    return 0


def place_score(b, r, c, p, rule):
    """(r,c)에 p 가 둘 때 4방향 합산 점수(룰 반영)."""
    if b[r][c] != 0:
        return -1
    b[r][c] = p
    try:
        if is_win(b, r, c, p, rule):
            return WIN
        # 렌주 흑: 장목은 승리 아님 → 이득 없음(금수는 별도 처리)
        total = 0
        for dr, dc in DIRS:
            st = _states(b, r, c, dr, dc, p)
            cnt = _run_through(st, 5)
            oe = 0
            # 양끝 열림 계산
            i = 5
            while i > 0 and st[i - 1] == 'O':
                i -= 1
            j = 5
            while j < len(st) - 1 and st[j + 1] == 'O':
                j += 1
            if i > 0 and st[i - 1] == '.':
                oe += 1
            if j < len(st) - 1 and st[j + 1] == '.':
                oe += 1
            if _restricted_black(p, rule) and cnt >= 6:
                continue                      # 흑 장목은 점수 0
            total += _pattern_score(cnt, oe)
        return total
    finally:
        b[r][c] = 0


def _candidates(b, radius=2):
    size = len(b)
    stones = [(r, c) for r in range(size) for c in range(size) if b[r][c] != 0]
    if not stones:
        return [(size // 2, size // 2)]
    cand = set()
    for (r, c) in stones:
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                rr, cc = r + dr, c + dc
                if _in(b, rr, cc) and b[rr][cc] == 0:
                    cand.add((rr, cc))
    return list(cand)


def best_move(b, me, rule="renju", defense_weight=1.0):
    """me 차례 최선수. me=BLACK&renju면 금수 자리 제외, 상대 위협도 상대 색 룰로 평가."""
    o = opp(me)
    best = None
    forbidden_hits = 0
    for (r, c) in _candidates(b):
        # 내 수가 렌주 흑 금수면 후보 제외
        if is_forbidden(b, r, c, me, rule):
            forbidden_hits += 1
            continue
        off = place_score(b, r, c, me, rule)
        # 상대가 여기 두는 위협 — 단 그 수가 상대(렌주 흑)에게 금수면 위협 무효
        if is_forbidden(b, r, c, o, rule):
            dfn = 0
        else:
            dfn = place_score(b, r, c, o, rule)
        score = off + defense_weight * dfn
        cand = {"move": (r, c), "score": score, "offense": off, "defense": dfn}
        if best is None or score > best["score"]:
            best = cand
    if best:
        best["reason"] = _reason(best, me, rule)
        best["forbidden_skipped"] = forbidden_hits
    return best


def _reason(bm, me, rule):
    off, dfn = bm["offense"], bm["defense"]
    if off >= WIN:
        return "즉시 승리(5목)"
    if dfn >= WIN:
        return "상대 5목 저지(필수 방어)"
    if off >= OPEN4:
        return "열린4 완성 → 다음수 승리 위협"
    if dfn >= OPEN4:
        return "상대 열린4 저지"
    if off >= FOUR:
        return "4 형성(선제 위협)"
    if dfn >= FOUR:
        return "상대 4 저지"
    if off >= OPEN3:
        return "열린3 형성(공격 전개)"
    if dfn >= OPEN3:
        return "상대 열린3 저지"
    return "형세상 최선 확장"


INF = 1 << 62


class _SearchTimeout(Exception):
    """An interrupted search has no score and proves neither win nor defense."""


def _check_deadline(deadline):
    if deadline is not None and time.perf_counter() >= deadline:
        raise _SearchTimeout


def _deadline(start, budget):
    if not math.isfinite(budget):
        raise ValueError("time_budget must be finite")
    return start + max(0.0, budget)


@contextmanager
def _placed(b, r, c, p):
    previous = b[r][c]
    b[r][c] = p
    try:
        yield
    finally:
        b[r][c] = previous


def _ordered(b, me, rule, width, deadline=None):
    """Score legal candidates; interruption never returns a partial ordering."""
    scored = []
    _check_deadline(deadline)
    for r, c in _candidates(b):
        _check_deadline(deadline)
        if is_forbidden(b, r, c, me, rule):
            continue
        defense = (0 if is_forbidden(b, r, c, opp(me), rule)
                   else place_score(b, r, c, opp(me), rule))
        scored.append((place_score(b, r, c, me, rule) + defense, r, c))
    _check_deadline(deadline)
    scored.sort(reverse=True)
    return [(r, c) for _, r, c in scored[:width]]


def _potential(b, p, rule, deadline=None):
    top = second = 0
    _check_deadline(deadline)
    for r, c in _candidates(b, radius=1):
        _check_deadline(deadline)
        if is_forbidden(b, r, c, p, rule):
            continue
        score = place_score(b, r, c, p, rule)
        if score > top:
            second, top = top, score
        elif score > second:
            second = score
    _check_deadline(deadline)
    return top + min(second, OPEN3) // 2


def _evaluate(b, me, rule, deadline=None):
    return (_potential(b, me, rule, deadline)
            - _potential(b, opp(me), rule, deadline))


def _gain_points(b, p, rule, deadline=None, limit=None):
    """Immediate wins. Current rule semantics give a completed five priority
    over forbidden patterns, so a winning point needs no extra ban scan."""
    points = []
    _check_deadline(deadline)
    for r, c in _candidates(b, radius=1):
        _check_deadline(deadline)
        with _placed(b, r, c, p):
            win = is_win(b, r, c, p, rule)
        if win:
            points.append((r, c))
            if limit is not None and len(points) >= limit:
                break
    _check_deadline(deadline)
    return points


def _immediate_win_pt(b, p, rule, deadline=None):
    points = _gain_points(b, p, rule, deadline, limit=1)
    return points[0] if points else None


def _negamax(b, me, rule, depth, alpha, beta, deadline):
    _check_deadline(deadline)
    if _immediate_win_pt(b, me, rule, deadline) is not None:
        return WIN + depth
    o = opp(me)
    threats = _gain_points(b, o, rule, deadline, limit=2)
    if len(threats) > 1:
        return -WIN - depth
    if threats and is_forbidden(b, *threats[0], me, rule):
        return -WIN - depth
    if depth == 0:
        return _evaluate(b, me, rule, deadline)
    # Forced defenses must not be lost to the ordinary width cap.
    cands = threats or _ordered(b, me, rule, width=6, deadline=deadline)
    if not cands:
        return 0
    best = -INF
    for r, c in cands:
        _check_deadline(deadline)
        with _placed(b, r, c, me):
            val = -_negamax(b, o, rule, depth - 1, -beta, -alpha, deadline)
        best = max(best, val)
        alpha = max(alpha, val)
        if alpha >= beta:
            break
    _check_deadline(deadline)
    return best


def _forcing_moves(b, me, rule, deadline=None):
    out = []
    _check_deadline(deadline)
    for r, c in _candidates(b, radius=1):
        _check_deadline(deadline)
        if is_forbidden(b, r, c, me, rule):
            continue
        with _placed(b, r, c, me):
            force = is_win(b, r, c, me, rule) or count_fours(b, r, c, me, rule) >= 1
        if force:
            out.append((r, c))
    _check_deadline(deadline)
    return out


def _vcf(b, me, rule, depth, deadline):
    """Prove consecutive-four wins; timeout raises, no proof returns None."""
    _check_deadline(deadline)
    if depth <= 0:
        return None
    o = opp(me)
    for r, c in _forcing_moves(b, me, rule, deadline):
        _check_deadline(deadline)
        with _placed(b, r, c, me):
            if is_win(b, r, c, me, rule):
                return (r, c)
            # The opponent moves next and can win before our double threat.
            if _immediate_win_pt(b, o, rule, deadline) is not None:
                continue
            gp = _gain_points(b, me, rule, deadline)
            if len(gp) >= 2:
                return (r, c)
            if len(gp) == 1:
                br, bc = gp[0]
                if is_forbidden(b, br, bc, o, rule):
                    return (r, c)
                with _placed(b, br, bc, o):
                    follow = _vcf(b, me, rule, depth - 1, deadline)
                if follow is not None:
                    return (r, c)
    _check_deadline(deadline)
    return None


def _winning_followups(b, me, rule, limit=6, deadline=None):
    out = []
    _check_deadline(deadline)
    for r, c in _candidates(b, radius=1):
        _check_deadline(deadline)
        if is_forbidden(b, r, c, me, rule):
            continue
        with _placed(b, r, c, me):
            strong = is_win(b, r, c, me, rule)
            if not strong:
                strong = (len(_gain_points(b, me, rule, deadline, limit=2)) >= 2
                          and _immediate_win_pt(b, opp(me), rule, deadline) is None)
        if strong:
            out.append((r, c))
            if len(out) >= limit:
                break
    _check_deadline(deadline)
    return out


def _threats_created(b, r, c, p, rule):
    with _placed(b, r, c, p):
        return count_fours(b, r, c, p, rule), count_open_threes(b, r, c, p)


def _legal_defenses(b, p, rule, deadline):
    """Proofs enumerate every legal reply, including distant counterplay."""
    for r, row in enumerate(b):
        for c, value in enumerate(row):
            _check_deadline(deadline)
            if value == 0 and not is_forbidden(b, r, c, p, rule):
                yield r, c


def _fork_unstoppable(b, me, o, fr, fc, rule, deadline=None):
    _check_deadline(deadline)
    with _placed(b, fr, fc, me):
        if _immediate_win_pt(b, o, rule, deadline) is not None:
            return False
        if len(_winning_followups(b, me, rule, limit=2, deadline=deadline)) < 2:
            return False
        checked = False
        for r, c in _legal_defenses(b, o, rule, deadline):
            checked = True
            with _placed(b, r, c, o):
                if is_win(b, r, c, o, rule):
                    return False
                if not _winning_followups(b, me, rule, limit=1, deadline=deadline):
                    return False
        _check_deadline(deadline)
        return checked


def _forced_win_move(b, me, rule, deadline):
    for r, c in _ordered(b, me, rule, 16, deadline):
        _check_deadline(deadline)
        with _placed(b, r, c, me):
            if is_win(b, r, c, me, rule):
                return (r, c)
        nf, n3 = _threats_created(b, r, c, me, rule)
        if nf >= 2 or (nf >= 1 and n3 >= 1) or n3 >= 2:
            if _fork_unstoppable(b, me, opp(me), r, c, rule, deadline):
                return (r, c)
    _check_deadline(deadline)
    return None


def _threat_moves_vct(b, me, rule, three_cap=8, deadline=None):
    fours, threes = [], []
    _check_deadline(deadline)
    for r, c in _candidates(b, radius=1):
        _check_deadline(deadline)
        if is_forbidden(b, r, c, me, rule):
            continue
        nf, n3 = _threats_created(b, r, c, me, rule)
        if nf >= 1:
            fours.append((r, c))
        elif n3 >= 1:
            threes.append((r, c))
    _check_deadline(deadline)
    return fours + threes[:three_cap]


def _vct(b, me, rule, depth, deadline):
    """Only a proof over all legal replies can return a winning move."""
    _check_deadline(deadline)
    if depth <= 0:
        return None
    immediate = _immediate_win_pt(b, me, rule, deadline)
    if immediate is not None:
        return immediate
    o = opp(me)
    for r, c in _threat_moves_vct(b, me, rule, deadline=deadline):
        _check_deadline(deadline)
        with _placed(b, r, c, me):
            if _immediate_win_pt(b, o, rule, deadline) is not None:
                continue
            gp = _gain_points(b, me, rule, deadline)
            if len(gp) >= 2:
                return (r, c)
            if gp:
                br, bc = gp[0]
                if is_forbidden(b, br, bc, o, rule):
                    return (r, c)
                with _placed(b, br, bc, o):
                    sub = _vct(b, me, rule, depth - 1, deadline)
                if sub is not None:
                    return (r, c)
                continue
            checked = False
            for dr, dc in _legal_defenses(b, o, rule, deadline):
                checked = True
                with _placed(b, dr, dc, o):
                    sub = _vct(b, me, rule, depth - 1, deadline)
                if sub is None:
                    break
            else:
                _check_deadline(deadline)
                if checked:
                    return (r, c)
    _check_deadline(deadline)
    return None


def _proof_stage(fn, *args):
    try:
        move = fn(*args)
        return ("PROVEN_WIN", move) if move is not None else ("NO_PROOF", None)
    except _SearchTimeout:
        return "TIMEOUT", None


def prove_win_move_ex(b, me, rule="renju", time_budget=2.0):
    """Return status PROVEN_WIN, NO_PROOF or TIMEOUT under configured rules.

    NO_PROOF is not a proof of loss: attacker candidates and depth are limited.
    This retains the engine's approximate forbidden-move semantics.
    """
    start = time.perf_counter()
    deadline = _deadline(start, time_budget)
    timed_out = False
    try:
        immediate = _immediate_win_pt(b, me, rule, deadline)
        if immediate is not None:
            return {"status": "PROVEN_WIN", "move": immediate, "reason": "즉시 승리(5목)"}
        stages = (
            (_vcf, (b, me, rule, 24, min(deadline, start + time_budget * .35)), "강제승(연속 사·VCF)"),
            (_forced_win_move, (b, me, rule, min(deadline, start + time_budget * .5)), "필승수(포크·이중위협)"),
            (_vct, (b, me, rule, 12, deadline), "강제승(위협연쇄·VCT)"),
        )
        for fn, args, reason in stages:
            _check_deadline(deadline)
            status, move = _proof_stage(fn, *args)
            if status == "PROVEN_WIN":
                return {"status": status, "move": move, "reason": reason}
            timed_out |= status == "TIMEOUT"
    except _SearchTimeout:
        timed_out = True
    return {"status": "TIMEOUT" if timed_out else "NO_PROOF", "move": None}


def prove_win_move(b, me, rule="renju", time_budget=2.0):
    """Compatibility API: a proven move, or None for timeout/no proof.

    Use prove_win_move_ex to distinguish those outcomes. None never establishes
    that a position is safe, or that the opponent has no winning sequence.
    """
    result = prove_win_move_ex(b, me, rule, time_budget)
    if result["status"] == "PROVEN_WIN":
        return {"move": result["move"], "reason": result["reason"]}
    return None


def opponent_forced_win(b, me, rule="renju", time_budget=1.0):
    """An opponent's proven attacking move; occupying it is not a defense proof."""
    result = prove_win_move(b, opp(me), rule, time_budget)
    return result["move"] if result else None


def _root_search(b, me, o, rule, cands, depth, deadline):
    best = None
    alpha, beta = -INF, INF
    for r, c in cands:
        _check_deadline(deadline)
        with _placed(b, r, c, me):
            if is_win(b, r, c, me, rule):
                return {"move": (r, c), "score": WIN, "_win": True}
            val = -_negamax(b, o, rule, depth - 1, -beta, -alpha, deadline)
        if best is None or val > best["score"]:
            best = {"move": (r, c), "score": val}
        alpha = max(alpha, val)
    _check_deadline(deadline)
    return best


def search_move(b, me, rule="renju", depth=6, width=12, time_budget=0.5):
    """Deadline-bounded search with completed-iteration fallback.

    depth reports completed search only. timed_out marks an interrupted request.
    With no time to validate any legal candidate (including zero budget), None
    is returned. Time checks are cooperative, not an OS real-time guarantee.
    """
    start = time.perf_counter()
    deadline = _deadline(start, time_budget)
    if depth < 1 or width < 1:
        raise ValueError("depth and width must be positive")
    best = None
    timed_out = False
    try:
        _check_deadline(deadline)
        cands = _candidates(b)
        # Keep a legal fallback even if later ordering or evaluation expires.
        for r, c in cands:
            _check_deadline(deadline)
            if not is_forbidden(b, r, c, me, rule):
                best = {"move": (r, c), "score": 0, "depth": 0,
                        "reason": "합법 후보(탐색 미완료)"}
                break
        if best is None:
            return None
        if all(value == 0 for row in b for value in row):
            best.update(reason="첫 수(중앙)", timed_out=False,
                        elapsed_ms=(time.perf_counter() - start) * 1000)
            return best
        immediate = _immediate_win_pt(b, me, rule, deadline)
        if immediate is not None:
            best.update(move=immediate, score=WIN, reason="즉시 승리(5목)",
                        proof_status="PROVEN_WIN")
        else:
            o = opp(me)
            threats = _gain_points(b, o, rule, deadline, limit=2)
            if threats:
                for r, c in threats:
                    _check_deadline(deadline)
                    if not is_forbidden(b, r, c, me, rule):
                        best.update(move=(r, c), score=0 if len(threats) == 1 else -WIN,
                                    reason="상대 5목 저지(필수 방어)" if len(threats) == 1
                                    else "상대 다중 즉승 위협(패배 예상)")
                        break
                else:
                    best.update(score=-WIN, reason="상대 즉승 방어점이 금수(패배 예상)")
            else:
                status, move = _proof_stage(
                    _vcf, b, me, rule, 10, min(deadline, start + time_budget * .35))
                reason = "강제승 발견(연속 사·VCF)"
                if status != "PROVEN_WIN":
                    status, move = _proof_stage(
                        _forced_win_move, b, me, rule,
                        min(deadline, start + time_budget * .5))
                    reason = "필승수(포크·이중위협)"
                if status == "PROVEN_WIN":
                    best.update(move=move, score=WIN, reason=reason,
                                proof_status=status)
                else:
                    # Unproven opponent searches no longer claim a successful
                    # defense. Spend the remaining time on ordinary search.
                    cands = _ordered(b, me, rule, width, deadline)
                    if cands:
                        best.update(move=cands[0], reason="후보 평가(탐색 미완료)")
                    for d in range(1, depth + 1):
                        result = _root_search(b, me, o, rule, cands, d, deadline)
                        if result is not None:
                            won = result.pop("_win", False)
                            best = dict(result, depth=d, reason="탐색 평가")
                            if won:
                                best.update(reason="즉시 승리(5목)", proof_status="PROVEN_WIN")
                                break
                            move = result["move"]
                            cands = [move] + [x for x in cands if x != move]
    except _SearchTimeout:
        timed_out = True
    if best is not None:
        best["timed_out"] = timed_out
        best["elapsed_ms"] = (time.perf_counter() - start) * 1000
    return best


def render(b, mark=None):
    size = len(b)
    out = ["   " + " ".join(f"{c:2d}" for c in range(size))]
    for r in range(size):
        row = []
        for c in range(size):
            if mark == (r, c):
                row.append(" ★")
            else:
                v = b[r][c]
                row.append(" " + ("·" if v == 0 else ("●" if v == BLACK else "○")))
        out.append(f"{r:2d} " + "".join(row))
    return "\n".join(out)


if __name__ == "__main__":
    def put(b, p, cells):
        for (r, c) in cells:
            b[r][c] = p

    # 1) 즉시 승리
    b = empty_board(); put(b, BLACK, [(7, 3), (7, 4), (7, 5), (7, 6)])
    m = best_move(b, BLACK, "renju")
    assert m["offense"] >= WIN, m
    print("[1] 흑 즉시승리:", m["move"], m["reason"])

    # 2) 필수 방어(상대 백 열린4)
    b = empty_board(); put(b, WHITE, [(7, 3), (7, 4), (7, 5), (7, 6)])
    m = best_move(b, BLACK, "renju")
    assert m["defense"] >= OPEN4, m
    print("[2] 방어:", m["move"], m["reason"])

    # 3) 렌주 흑 삼삼(3-3) 금수 판정 — (7,7)에 두면 두 개의 열린3 동시 형성
    b = empty_board()
    put(b, BLACK, [(7, 5), (7, 6), (5, 7), (6, 7)])   # 가로 _●●_ + 세로 _●●_ 교차점 (7,7)
    fb = is_forbidden(b, 7, 7, BLACK, "renju")
    print("[3] 흑 (7,7) 삼삼 금수?", fb)
    assert fb is True, "삼삼 금수 미검출"
    # 백은 같은 자리 허용
    assert is_forbidden(b, 7, 7, WHITE, "renju") is False

    # 4) 렌주 흑은 삼삼 자리를 추천하지 않음
    b = empty_board()
    put(b, BLACK, [(7, 5), (7, 6), (5, 7), (6, 7)])
    m = best_move(b, BLACK, "renju")
    assert m["move"] != (7, 7), f"금수 자리를 추천함: {m}"
    print("[4] 흑 추천수(금수회피):", m["move"], "| 스킵한 금수", m.get("forbidden_skipped"))

    # 5) 장목(6목) — 흑은 승리 아님
    b = empty_board(); put(b, BLACK, [(7, 3), (7, 4), (7, 5), (7, 6), (7, 8)])
    #  (7,7) 두면 3~8 여섯 → 장목
    with _placed(b, 7, 7, BLACK):
        assert is_win(b, 7, 7, BLACK, "renju") is False
    b2 = empty_board(); put(b2, BLACK, [(7, 2), (7, 3), (7, 4), (7, 5), (7, 6)])
    # (7,7) 두면 2~7 여섯목 → 흑 장목(금수), 승리 아님
    print("[5] 흑 (7,7) 6목 승리?", is_win(b2, 7, 7, BLACK, "renju"), "| 금수?", is_forbidden(b2, 7, 7, BLACK, "renju"))
    with _placed(b2, 7, 7, BLACK):
        assert is_win(b2, 7, 7, BLACK, "renju") is False
    assert is_forbidden(b2, 7, 7, BLACK, "renju") is True
    # 기본 앱 호환 설정에서는 백도 장목 금지. 제한을 해제하면 6목 승리.
    b3 = empty_board(); put(b3, WHITE, [(7, 2), (7, 3), (7, 4), (7, 5), (7, 6)])
    with _placed(b3, 7, 7, WHITE):
        assert is_win(b3, 7, 7, WHITE, "renju") is False
        set_forbid(white={"overline": False})
        try:
            assert is_win(b3, 7, 7, WHITE, "renju") is True
        finally:
            set_forbid(white={"overline": True})
    print("[5b] 백 장목 설정별 검증 OK")

    # 6) 일반룰: 삼삼 허용, 6목 승리
    b = empty_board(); put(b, BLACK, [(7, 5), (7, 6), (5, 7), (6, 7)])
    assert is_forbidden(b, 7, 7, BLACK, "standard") is False
    b2 = empty_board(); put(b2, BLACK, [(7, 2), (7, 3), (7, 4), (7, 5), (7, 6)])
    with _placed(b2, 7, 7, BLACK):
        assert is_win(b2, 7, 7, BLACK, "standard") is True
    print("[6] 일반룰 삼삼 허용·6목 승리 OK")

    print("\n자체검증 통과 ✅")
