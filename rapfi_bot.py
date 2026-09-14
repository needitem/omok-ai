#!/usr/bin/env python3
"""rapfi_bot.py — Rapfi(대회급 NNUE 오목엔진) subprocess 래퍼 (pbrain 프로토콜).

best_move(board, me, rule, timeout_ms) → (row, col) 또는 None. 읽기 전용 훈수용.
좌표: config coord_conversion_mode="none" → pbrain (x,y)=(col,row). 우리 board[row][col].
rule: 일반룰(흑 금수)≈renju(코드2). board 셀 1=흑,2=백,0=빈 / me=내 색(1 or 2).
"""
from __future__ import annotations
import subprocess, threading, os, re, time

ENGINE_DIR = os.environ.get("RAPFI_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "rapfi_engine")
ENGINE_BIN = os.path.join(ENGINE_DIR, "pbrain-rapfi")
SIZE = 15
_RULE = {"korean": 2, "renju": 2, "standard": 1, "freestyle": 0}   # 일반룰≈renju(흑 금수)
_COORD = re.compile(r"^(\d+),(\d+)\s*$")
_ALG = re.compile(r"^([A-Oa-o])(\d{1,2})$")   # Rapfi PV 좌표(대수표기): 열 A-O, 행 1-15


def _alg2rc(tok):
    """Rapfi 대수표기 'G7' → (row,col). 열=A..O(0..14), 행=1..15→0-index. 범위 밖이면 None."""
    m = _ALG.match(tok)
    if not m:
        return None
    col = ord(m.group(1).upper()) - 65
    row = int(m.group(2)) - 1
    return (row, col) if (0 <= row < SIZE and 0 <= col < SIZE) else None


class Rapfi:
    def __init__(self):
        self.p = None
        self.lock = threading.Lock()
        self.rule = None

    def _start(self):
        self.p = subprocess.Popen(
            [ENGINE_BIN], cwd=ENGINE_DIR,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self._send(f"START {SIZE}")
        self._read_until("OK", 15)
        self.rule = None

    def _send(self, line):
        self.p.stdin.write(line + "\n"); self.p.stdin.flush()

    def _read_until(self, token, timeout):
        t = time.time()
        while time.time() - t < timeout:
            ln = self.p.stdout.readline()
            if not ln:
                raise RuntimeError("engine closed")
            if ln.strip() == token:
                return
        raise RuntimeError(f"timeout waiting {token}")

    def _read_result(self, timeout):
        """엔진 출력에서 최종 수 + PV(예상수순, [(row,col)...]) + eval 을 뽑는다.
        MESSAGE(탐색 진행) 라인에서 마지막 PV/Eval 을 기억하다가 좌표 라인이 나오면 확정."""
        t = time.time(); pv = []; ev = None
        while time.time() - t < timeout:
            ln = self.p.stdout.readline()
            if not ln:
                raise RuntimeError("engine closed")
            s = ln.strip()
            if s.startswith("MESSAGE"):
                if "Eval" in s:
                    m = re.search(r"Eval\s+(\S+)", s)
                    if m:
                        ev = m.group(1)
                    cand = []                                 # 마지막 '|' 세그먼트가 전부 좌표면 = PV
                    for tk in s.split("|")[-1].strip().split():
                        rc = _alg2rc(tk)
                        if rc is None:
                            cand = []; break
                        cand.append(rc)
                    if cand:
                        pv = cand
                continue
            m = _COORD.match(s)
            if m:
                return (int(m.group(1)), int(m.group(2))), pv, ev   # (x=col,y=row), pv, eval
        raise RuntimeError("no move (timeout)")

    def _search(self, board, rule, timeout_ms):
        """→ {'move':(row,col), 'pv':[(row,col)...], 'eval':str} 또는 None."""
        code = _RULE.get(rule, 2)
        with self.lock:
            for attempt in (1, 2):
                try:
                    if self.p is None or self.p.poll() is not None:
                        self._start()
                    if self.rule != code:
                        self._send(f"INFO rule {code}"); self.rule = code
                    self._send(f"INFO timeout_turn {int(timeout_ms)}")
                    self._send("BOARD")
                    n = len(board)
                    # ★절대색(1=흑,2=백): Rapfi renju 는 pbrain 값 1을 '흑(금수대상)'으로 고정 취급.
                    #  ★★차례 판정: Rapfi 는 BOARD 의 '돌 나열 순서(마지막 돌 색)'로 수번(차례)을 추론한다.
                    #   스캔순서로 보내면 마지막 돌이 임의 색 → Rapfi 가 반대편 수를 계산하는 치명버그.
                    #   → 흑,백,흑,백… '교대순'(흑 먼저)으로 보내 차례를 정확히 인코딩한다.
                    #   흑차례(nb==nw): …흑,백 로 끝(백 마지막) → 다음 흑. 백차례(nb==nw+1): …흑 로 끝 → 다음 백.
                    blacks = [(r, c) for r in range(n) for c in range(n) if board[r][c] == 1]
                    whites = [(r, c) for r in range(n) for c in range(n) if board[r][c] == 2]
                    for i in range(max(len(blacks), len(whites))):
                        if i < len(blacks):
                            r, c = blacks[i]; self._send(f"{c},{r},1")   # x=col,y=row
                        if i < len(whites):
                            r, c = whites[i]; self._send(f"{c},{r},2")
                    self._send("DONE")
                    (x, y), pv, ev = self._read_result(timeout_ms / 1000.0 + 8)
                    return {"move": (y, x), "pv": pv, "eval": ev}   # (row,col)
                except Exception:
                    try:
                        self.p.kill()
                    except Exception:
                        pass
                    self.p = None
                    if attempt == 2:
                        return None
        return None

    def best_move(self, board, me, rule="korean", timeout_ms=400):
        r = self._search(board, rule, timeout_ms)
        return r["move"] if r else None


_ENGINE = None
def _engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = Rapfi()
    return _ENGINE

def available() -> bool:
    return os.path.exists(ENGINE_BIN)

def best_move_ex(board, me, rule="korean", timeout_ms=400):
    """{'move':(row,col), 'pv':[(row,col)...예상수순], 'eval':str} 또는 None."""
    if not available():
        return None
    return _engine()._search(board, rule, timeout_ms)

def best_move(board, me, rule="korean", timeout_ms=400):
    """(row,col) 최선수 또는 None."""
    r = best_move_ex(board, me, rule, timeout_ms)
    return r["move"] if r else None


if __name__ == "__main__":
    # 자체 테스트: 방어(상대 4목 유일 완성점 막기), 좌표 검증
    b = [[0] * 15 for _ in range(15)]
    # 상대(백=2) 가로4 row9 col3~6, 한쪽(col2) 내(흑=1) 막음 → 유일 완성점 (row9,col7) 막아야
    for c in (3, 4, 5, 6):
        b[9][c] = 2
    b[9][2] = 1
    mv = best_move(b, 1, "korean", 400)   # 내가 흑(1), 내 차례
    print("방어 추천 (기대 (9,7)):", mv)
    # 공격: 내(흑=1) 가로4 row7 col3~6 → 완성 (7,7) or (7,2)
    b2 = [[0] * 15 for _ in range(15)]
    for c in (3, 4, 5, 6):
        b2[7][c] = 1
    print("공격 추천 (기대 (7,7)/(7,2)):", best_move(b2, 1, "korean", 400))
