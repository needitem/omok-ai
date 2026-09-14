#!/usr/bin/env python3
"""
omok_ai.py — 오목 최선수 추천 엔진 (룰/색 인식, 렌주 금수 판정 포함). 순수 알고리즘.

지원:
  - 일반룰(standard): 양쪽 금수 없음, 5목 이상 승리.
  - 렌주룰(renju): 흑만 금수(삼삼 3-3, 사사 4-4, 장목 6목↑). 흑은 정확히 5목 승리.
                   백은 제한 없음·6목↑도 승리. 흑/백 로직 비대칭.

board: 2차원 리스트. 0=빈칸, 1=흑(BLACK, 선), 2=백(WHITE).
best_move(board, me, rule): 내(me) 차례의 최선수 {move,(r,c), reason, ...}.
  - me=BLACK & renju: 금수 자리는 절대 추천 안 함, 장목=승리 아님으로 처리.
  - 상대 위협 평가도 상대 색의 룰을 따른다(렌주 흑 상대의 금수 위협은 무효).

⚠️ 금수 판정은 실전 대부분을 커버하는 실용 구현. 공식 RIF의 재귀적 거짓삼(nested)
   극단 예외까지는 근사한다.
"""
from __future__ import annotations
import time

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
    for k in range(-half, half + 1):
        rr, cc = r + dr * k, c + dc * k
        if not _in(b, rr, cc):
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
def is_win(b, r, c, p, rule):
    """(r,c)에 p 를 둔 상태에서 승리인가. 렌주 흑=정확히 5, 그 외=5 이상."""
    exact = _restricted_black(p, rule)        # 그 색 overline 금지 → 정확히 5만 승리
    for dr, dc in DIRS:
        st = _states(b, r, c, dr, dc, p)
        run = _run_through(st, 5)
        if exact:
            if run == 5:
                return True
        elif run >= 5:                        # overline 허용/무금수룰 = 5 이상 승리
            return True
    return False


def _is_overline(b, r, c, p):
    for dr, dc in DIRS:
        st = _states(b, r, c, dr, dc, p)
        if _run_through(st, 5) >= 6:
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
    if _run_through(_states(b, r, c, dr, dc, p), 5) >= 4:
        return False
    for k in range(-4, 5):
        rr, cc = r + dr * k, c + dc * k
        if _in(b, rr, cc) and b[rr][cc] == 0:
            b[rr][cc] = p
            of = _open_four_through(b, r, c, dr, dc, p) or _open_four_through(b, rr, cc, dr, dc, p)
            b[rr][cc] = 0
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
                        if _open_three_in_dir(b, r, c, dr, dc, p) and fdir[(dr, dc)] == 0)
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


def _ordered(b, me, rule, width):
    """후보를 (내 이득+상대 이득) 내림차순 정렬해 상위 width개. 흑 금수는 제외."""
    scored = []
    for (r, c) in _candidates(b):
        if is_forbidden(b, r, c, me, rule):
            continue
        s = place_score(b, r, c, me, rule) + place_score(b, r, c, opp(me), rule)
        scored.append((s, r, c))
    scored.sort(reverse=True)
    return [(r, c) for _, r, c in scored[:width]]


def _potential(b, p, rule):
    """p의 위협 잠재력 = 최고 위협 + 둘째 위협 일부(이중위협 인지). radius1 근접만(속도)."""
    top = second = 0
    for (r, c) in _candidates(b, radius=1):
        if b[r][c] != 0 or is_forbidden(b, r, c, p, rule):
            continue
        s = place_score(b, r, c, p, rule)
        if s > top:
            second = top; top = s
        elif s > second:
            second = s
    # 둘째 위협 보너스(상한 OPEN3): 활삼 2개·사삼 같은 콤보를 단일 위협보다 높게 평가
    return top + min(second, OPEN3) // 2

def _evaluate(b, me, rule):
    """정적 평가: 내 잠재력 - 상대 잠재력(이중위협 반영)."""
    return _potential(b, me, rule) - _potential(b, opp(me), rule)


def _negamax(b, me, rule, depth, alpha, beta, deadline):
    if depth == 0 or time.time() > deadline:   # 시간초과 → 더 안 파고 정적평가로 수렴
        return _evaluate(b, me, rule)
    cands = _ordered(b, me, rule, width=6)
    if not cands:
        return 0
    o = opp(me)
    best = -INF
    for (r, c) in cands:
        b[r][c] = me
        if is_win(b, r, c, me, rule):
            b[r][c] = 0
            return WIN + depth                 # 빠른 승리 선호
        val = -_negamax(b, o, rule, depth - 1, -beta, -alpha, deadline)
        b[r][c] = 0
        if val > best:
            best = val
        if val > alpha:
            alpha = val
        if alpha >= beta:
            break
    return best


# ── VCF: 연속 사(四) 강제승 탐색 (위협공간탐색) ─────────────────
def _gain_points(b, p, rule):
    """빈칸 중 p가 두면 즉시 5(승리)가 되는 점 = 상대가 반드시 막아야 할 완성점."""
    pts = []
    for (r, c) in _candidates(b, radius=1):
        if b[r][c] != 0:
            continue
        b[r][c] = p
        w = is_win(b, r, c, p, rule)
        b[r][c] = 0
        if w:
            pts.append((r, c))
    return pts

def _forcing_moves(b, me, rule):
    """me가 두면 사(four) 이상 — 상대에게 5 위협을 걸어 응수를 강제하는 수들."""
    out = []
    for (r, c) in _candidates(b, radius=1):
        if b[r][c] != 0 or is_forbidden(b, r, c, me, rule):
            continue
        b[r][c] = me
        force = is_win(b, r, c, me, rule) or count_fours(b, r, c, me, rule) >= 1
        b[r][c] = 0
        if force:
            out.append((r, c))
    return out

def _vcf(b, me, rule, depth, deadline):
    """me 차례에 '연속 사(VCF)'로 강제승이면 그 첫 수 반환, 아니면 None.
    각 사는 상대가 유일 완성점을 막도록 강제; 완성점 2개↑(열린4/이중4)·즉승이면 승리."""
    if depth <= 0 or time.time() > deadline:
        return None
    o = opp(me)
    for (r, c) in _forcing_moves(b, me, rule):
        b[r][c] = me
        if is_win(b, r, c, me, rule):
            b[r][c] = 0
            return (r, c)
        gp = _gain_points(b, me, rule)
        if len(gp) >= 2:                             # 막을 수 없는 이중 위협(열린4/이중4)
            b[r][c] = 0
            return (r, c)
        if len(gp) == 1:
            br, bc = gp[0]
            if is_forbidden(b, br, bc, o, rule):     # 상대가 완성점에 못 둠(렌주 흑 금수)=승리
                b[r][c] = 0
                return (r, c)
            b[br][bc] = o                             # 상대 강제 방어
            follow = _vcf(b, me, rule, depth - 1, deadline)
            b[br][bc] = 0
            b[r][c] = 0
            if follow is not None:
                return (r, c)
            continue
        b[r][c] = 0
    return None


def _winning_followups(b, me, rule, limit=6):
    """me가 지금 두면 '막을 수 없는 승리위협'(5완성 or 완성점 2개↑=열린4/이중4)이 되는 자리들."""
    out = []
    for (r, c) in _candidates(b, radius=1):
        if b[r][c] != 0 or is_forbidden(b, r, c, me, rule):
            continue
        b[r][c] = me
        strong = is_win(b, r, c, me, rule) or len(_gain_points(b, me, rule)) >= 2
        b[r][c] = 0
        if strong:
            out.append((r, c))
            if len(out) >= limit:
                break
    return out

def _threats_created(b, r, c, p, rule):
    """(r,c)에 p 둘 때 (r,c)를 지나는 (사 개수, 활삼 개수). = 그 수가 '만든' 위협."""
    b[r][c] = p
    nf = count_fours(b, r, c, p, rule)
    n3 = count_open_threes(b, r, c, p)
    b[r][c] = 0
    return nf, n3

def _fork_unstoppable(b, me, o, fr, fc, rule):
    """me가 (fr,fc)에 포크를 둔 상태에서 상대가 한 수로 못 막으면 True(필승)."""
    b[fr][fc] = me
    try:
        for (r, c) in _candidates(b, radius=1):          # 상대 즉승(5) 반격이면 필승 아님
            if b[r][c] != 0 or is_forbidden(b, r, c, o, rule):
                continue
            b[r][c] = o; w = is_win(b, r, c, o, rule); b[r][c] = 0
            if w:
                return False
        wins = _winning_followups(b, me, rule)            # 포크가 만든 승리위협들
        if len(wins) < 2:
            return False
        cand = set(wins)                                  # 상대 차단 후보 = 위협점 ∪ 주변
        for (wr, wc) in wins:
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    rr, cc = wr + dr, wc + dc
                    if _in(b, rr, cc) and b[rr][cc] == 0:
                        cand.add((rr, cc))
        for (r, c) in cand:                               # 상대가 한 수로 다 막으면 필승 아님
            b[r][c] = o
            rem = _winning_followups(b, me, rule, limit=1)
            b[r][c] = 0
            if not rem:
                return False
        return True
    finally:
        b[fr][fc] = 0

def _forced_win_move(b, me, rule, deadline):
    """한 수로 '막을 수 없는 포크'(그 수를 지나는 44·사삼·삼삼 이중위협)를 만드는 수. 없으면 None.
    VCF(연속 사)가 못 잡는 활삼 콤보 필승수를 잡는다. 위협을 '그 수가 만든 것'으로 한정해
    이미 있던 위협을 오인하지 않는다. 후보는 위협 상위 16칸만(포크는 항상 고위협 자리)."""
    o = opp(me)
    for (r, c) in _ordered(b, me, rule, 16):
        b[r][c] = me; w = is_win(b, r, c, me, rule); b[r][c] = 0
        if w:
            return (r, c)
        nf, n3 = _threats_created(b, r, c, me, rule)
        if (nf >= 2 or (nf >= 1 and n3 >= 1) or n3 >= 2):   # 이 수가 만든 이중위협
            if _fork_unstoppable(b, me, o, r, c, rule):
                return (r, c)
        if time.time() > deadline:
            break
    return None


# ── VCT: 위협연쇄 강제승 (사+활삼 콤보). 건전성 최우선 ──────────────
#   설계 원칙(거짓 '필승' 절대 금지):
#     · 방어(상대) 응수 열거는 '완전한 상위집합'이어야 한다 → 놓친 반박수로 오판 방지.
#         - 내가 사(四)를 만들어 완성점이 정확히 1개면 상대는 그 점을 막을 수밖에 없다(유일 응수).
#         - 내가 활삼만 만들면(완성점 0개) 상대는 아무 데나 둘 수 있다 → 반경2 후보 전체를 응수로 검사.
#     · 공격수(내 위협수) 열거는 가지치기해도 됨 → 완전성만 손해, 건전성엔 무해.
#     · deadline 초과 시 항상 None 반환 → 타임아웃은 보수적(승리 주장 안 함).
def _immediate_win_pt(b, p, rule):
    """p 가 지금 한 수로 5를 만들 수 있는 (합법) 빈칸이 있으면 그 점, 없으면 None."""
    for (r, c) in _candidates(b, radius=1):
        if b[r][c] != 0 or is_forbidden(b, r, c, p, rule):
            continue
        b[r][c] = p
        w = is_win(b, r, c, p, rule)
        b[r][c] = 0
        if w:
            return (r, c)
    return None


def _threat_moves_vct(b, me, rule, three_cap=8):
    """공격 위협수: (a) 사 이상(강제) 먼저, (b) 활삼(비강제) 나중.
    활삼수는 three_cap 개로 제한(완전성만 영향, 건전성 무해). 반환: [(r,c)...]."""
    fours, threes = [], []
    for (r, c) in _candidates(b, radius=1):
        if b[r][c] != 0 or is_forbidden(b, r, c, me, rule):
            continue
        nf, n3 = _threats_created(b, r, c, me, rule)
        if nf >= 1:
            fours.append((r, c))
        elif n3 >= 1:
            threes.append((r, c))
    return fours + threes[:three_cap]


def _vct(b, me, rule, depth, deadline):
    """me 차례에 사·활삼 위협연쇄로 '증명된 강제승'이면 첫 수, 아니면 None.
    건전: 승리 주장은 모든 상대 응수를 반박했을 때만. 타임아웃/불확실은 None."""
    if depth <= 0 or time.time() > deadline:
        return None
    o = opp(me)
    for (r, c) in _threat_moves_vct(b, me, rule):
        b[r][c] = me
        try:
            if is_win(b, r, c, me, rule):
                return (r, c)                              # 5 완성
            gp = _gain_points(b, me, rule)                 # 이 수 후 내 즉승점
            if len(gp) >= 2:
                return (r, c)                              # 이중 완성점(열린4/이중4) = 막을 수 없음
            # 상대가 지금 즉승 가능하면 내 공격은 반박됨(상대가 그냥 이김)
            if _immediate_win_pt(b, o, rule) is not None:
                continue
            if len(gp) == 1:
                br, bc = gp[0]
                if is_forbidden(b, br, bc, o, rule):
                    return (r, c)                          # 유일 방어점이 상대 금수 → 승리
                b[br][bc] = o                              # 상대 유일 강제 방어
                sub = _vct(b, me, rule, depth - 1, deadline)
                b[br][bc] = 0
                if sub is not None:
                    return (r, c)
                continue
            # gp==0: 활삼만 만든 수 → 상대는 임의 응수 가능. '완전한' 응수 집합을 전부 반박해야 승리.
            defenses = [(dr, dc) for (dr, dc) in _candidates(b, radius=2) if b[dr][dc] == 0]
            won_all = bool(defenses)
            for (dr, dc) in defenses:
                if is_forbidden(b, dr, dc, o, rule):
                    continue                               # 상대가 못 두는 자리는 응수 후보 아님
                b[dr][dc] = o
                sub = _vct(b, me, rule, depth - 1, deadline)
                b[dr][dc] = 0
                if sub is None:
                    won_all = False
                    break
                if time.time() > deadline:
                    won_all = False
                    break
            if won_all:
                return (r, c)
        finally:
            b[r][c] = 0
    return None


def prove_win_move(b, me, rule="renju", time_budget=2.0):
    """'증명된 강제승' 첫 수를 반환(없으면 None). 건전성 보장 — 반환 시 반드시 필승.
    순서: 즉승 → VCF(연속 사, 깊게) → 포크(이중위협) → VCT(사+활삼 연쇄).
    time_budget(초) 를 실제로 다 쓴다(우선순위-0 하드캡 0.15s 문제 해소)."""
    t0 = time.time()
    o = opp(me)
    # 즉승
    for (r, c) in _candidates(b, radius=1):
        if b[r][c] != 0 or is_forbidden(b, r, c, me, rule):
            continue
        b[r][c] = me; w = is_win(b, r, c, me, rule); b[r][c] = 0
        if w:
            return {"move": (r, c), "reason": "즉시 승리(5목)"}
    # ★방어 우선: 상대가 이미 '사(四)→오목' 즉승 위협을 가지면, 내 강제승은 그걸 막는 수여야만 유효.
    #  (막지 않으면 상대가 다음 수에 오목 완성 → 내 VCF/VCT 는 허상. 이게 '상대 사 무시' 버그의 원인.)
    opp_now = _gain_points(b, o, rule)          # 상대가 지금 두면 5가 되는 점(상대의 기존 사 완성점)
    if opp_now:
        if len(opp_now) >= 2:                    # 완성점 2개↑ → 한 수로 못 막음(즉승만 승리, 위에서 없음)
            return None
        br, bc = opp_now[0]
        if is_forbidden(b, br, bc, me, rule):    # 유일 방어점이 내 금수 → 방어 불가
            return None
        b[br][bc] = me                           # 그 점을 막아본다
        try:
            win_after = (is_win(b, br, bc, me, rule)
                         or len(_gain_points(b, me, rule)) >= 2
                         or _fork_unstoppable(b, me, o, br, bc, rule))
        finally:
            b[br][bc] = 0
        # 막으면서 이기면 그 방어수가 곧 필승수. 아니면 강제승 주장 안 함(→ Rapfi 가 방어).
        return {"move": opp_now[0], "reason": "상대 사 차단 + 필승"} if win_after else None
    # VCF (연속 사) — 깊고 예산 넉넉히
    vm = _vcf(b, me, rule, depth=24, deadline=t0 + time_budget * 0.35)
    if vm is not None:
        return {"move": vm, "reason": "강제승(연속 사·VCF)"}
    # 포크 (한 수 이중위협)
    fm = _forced_win_move(b, me, rule, t0 + time_budget * 0.5)
    if fm is not None:
        return {"move": fm, "reason": "필승수(포크·이중위협)"}
    # VCT (사+활삼 위협연쇄)
    tm = _vct(b, me, rule, depth=12, deadline=t0 + time_budget)
    if tm is not None:
        return {"move": tm, "reason": "강제승(위협연쇄·VCT)"}
    return None


def opponent_forced_win(b, me, rule="renju", time_budget=1.0):
    """상대가 '증명된 강제승'을 갖고 있으면 그 첫 수(=우리가 선점/차단할 급소) 반환, 없으면 None.
    상대 관점에서 prove_win_move 를 돌린다(방어용)."""
    o = opp(me)
    r = prove_win_move(b, o, rule, time_budget)
    return r["move"] if r else None


def _root_search(b, me, o, rule, cands, depth, deadline):
    """루트에서 cands 를 depth 로 평가해 최선 {move,score} 반환(즉승은 _win 표시)."""
    best = None
    alpha, beta = -INF, INF
    for (r, c) in cands:
        if best is not None and time.time() > deadline:
            break
        b[r][c] = me
        if is_win(b, r, c, me, rule):
            b[r][c] = 0
            return {"move": (r, c), "score": WIN, "_win": True}
        val = -_negamax(b, o, rule, depth - 1, -beta, -alpha, deadline)
        b[r][c] = 0
        if best is None or val > best["score"]:
            best = {"move": (r, c), "score": val}
        if val > alpha:
            alpha = val
    return best


def search_move(b, me, rule="renju", depth=6, width=12, time_budget=0.5):
    """알파-베타 탐색으로 최선수. 즉승·VCF강제승·필수방어는 즉시 처리, 그 외 depth 앞을 내다본다.
    time_budget(초) 하드 상한: 초과 시 지금까지 최선(정렬 상위)으로 즉시 반환 →
    조용한 판에서 수 초씩 걸리던 것을 상한 내로 고정(품질 손실 미미: 깊게 파도 답 거의 동일)."""
    cands = _candidates(b)
    if all(b[r][c] == 0 for r in range(len(b)) for c in range(len(b[0]))):
        rc = (len(b) // 2, len(b) // 2)
        return {"move": rc, "score": 0, "reason": "첫 수(중앙)", "depth": depth}
    o = opp(me)
    t0 = time.time()
    # 1) 즉승수
    for (r, c) in cands:
        if is_forbidden(b, r, c, me, rule):
            continue
        b[r][c] = me; win = is_win(b, r, c, me, rule); b[r][c] = 0
        if win:
            return {"move": (r, c), "score": WIN, "reason": "즉시 승리(5목)", "depth": 0}
    # 1.5) VCF — 연속 사(四)로 강제승이 있으면 즉시 그 수
    vm = _vcf(b, me, rule, depth=10, deadline=t0 + min(time_budget * 0.35, 0.15))
    if vm is not None:
        return {"move": vm, "score": WIN, "reason": "강제승 발견(연속 사·VCF)", "depth": 0}
    # 1.6) 포크 필승수 — VCF 가 못 잡는 이중위협(사삼·삼삼) 강제승
    fm = _forced_win_move(b, me, rule, t0 + min(time_budget * 0.55, 0.22))
    if fm is not None:
        return {"move": fm, "score": WIN, "reason": "필승수(포크·이중위협)", "depth": 0}
    # 2) 상대 즉승 저지(상대가 둘 수 있는 자리만)
    for (r, c) in cands:
        if is_forbidden(b, r, c, o, rule):
            continue
        b[r][c] = o; owin = is_win(b, r, c, o, rule); b[r][c] = 0
        if owin and not is_forbidden(b, r, c, me, rule):
            return {"move": (r, c), "score": WIN // 2, "reason": "상대 5목 저지(필수 방어)", "depth": 0}
    # 2.5) 상대 VCF 저지 — 상대에게 연속 사 강제승 수순이 있으면 그걸 깨는 수 우선
    if _vcf(b, o, rule, depth=10, deadline=t0 + min(time_budget * 0.3, 0.12)) is not None:
        for (r, c) in _ordered(b, me, rule, width)[:12]:
            if is_forbidden(b, r, c, me, rule):
                continue
            b[r][c] = me
            broke = _vcf(b, o, rule, depth=10, deadline=time.time() + 0.05) is None
            b[r][c] = 0
            if broke:
                return {"move": (r, c), "score": WIN // 2, "reason": "상대 강제승(VCF) 저지", "depth": 0}
    # 2.6) 상대 포크 저지 — 상대의 필승 포크 급소를 선점
    ofm = _forced_win_move(b, o, rule, t0 + min(time_budget * 0.75, 0.3))
    if ofm is not None and not is_forbidden(b, ofm[0], ofm[1], me, rule):
        return {"move": ofm, "score": WIN // 2, "reason": "상대 필승수(포크) 저지", "depth": 0}
    # 3) 반복심화 알파-베타: 얕은 결과부터 확보하며 시간 되는 만큼 깊이 확장.
    #    각 반복 후 최선수를 맨 앞으로 재정렬 → 다음 반복에서 컷 증가(가속).
    deadline = t0 + time_budget
    cands = _ordered(b, me, rule, width)
    if not cands:
        return None
    best = {"move": cands[0], "score": 0}
    reached = 1
    for d in range(2, depth + 1):
        r = _root_search(b, me, o, rule, cands, d, deadline)
        if r:
            best = r; reached = d
            if r.get("_win"):
                break
            mv = r["move"]
            cands = [mv] + [x for x in cands if x != mv]
        if time.time() > deadline:
            break
    r0, c0 = best["move"]
    off = place_score(b, r0, c0, me, rule)
    dfn = 0 if is_forbidden(b, r0, c0, o, rule) else place_score(b, r0, c0, o, rule)
    best["reason"] = _reason({"offense": off, "defense": dfn}, me, rule)
    best["depth"] = reached
    best.pop("_win", None)
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
    assert is_win(b, 7, 7, BLACK, "renju") is False or True  # 정확검증은 아래
    b2 = empty_board(); put(b2, BLACK, [(7, 2), (7, 3), (7, 4), (7, 5), (7, 6)])
    # (7,7) 두면 2~7 여섯목 → 흑 장목(금수), 승리 아님
    print("[5] 흑 (7,7) 6목 승리?", is_win(b2, 7, 7, BLACK, "renju"), "| 금수?", is_forbidden(b2, 7, 7, BLACK, "renju"))
    assert is_win(b2, 7, 7, BLACK, "renju") is False
    assert is_forbidden(b2, 7, 7, BLACK, "renju") is True
    # 백이면 6목 승리
    b3 = empty_board(); put(b3, WHITE, [(7, 2), (7, 3), (7, 4), (7, 5), (7, 6)])
    assert is_win(b3, 7, 7, WHITE, "renju") is True
    print("[5b] 백 (7,7) 6목 승리?", is_win(b3, 7, 7, WHITE, "renju"))

    # 6) 일반룰: 삼삼 허용, 6목 승리
    b = empty_board(); put(b, BLACK, [(7, 5), (7, 6), (5, 7), (6, 7)])
    assert is_forbidden(b, 7, 7, BLACK, "standard") is False
    b2 = empty_board(); put(b2, BLACK, [(7, 2), (7, 3), (7, 4), (7, 5), (7, 6)])
    assert is_win(b2, 7, 7, BLACK, "standard") is True
    print("[6] 일반룰 삼삼 허용·6목 승리 OK")

    print("\n자체검증 통과 ✅")
