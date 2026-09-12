# -*- coding: utf-8 -*-
"""Pipes（接水管）求解器：纯规则推理，不搜索、不枚举、不回溯。

按两层结构维护状态：
1. 格子状态网格 self.poss[(x, y)] = 该格还可能的形状集合（4-bit 管道掩码）。
   集合只剩 1 个元素时该格"确定"。
2. 连接状态数组 self.edges：相邻两格之间的边 -> 1 确定需要连接 / -1 确定是墙，
   缺省 0 未确定。

坐标：x 向右、y 向下，内部从 0 起；对外展示按习惯从 1 起（左上角 = (1,1)）。
掩码位（对照游戏源码 dc=[1,0,-1,0], dr=[0,-1,0,1] 确认）：1=右 2=上 4=左 8=下。

每应用一条规则记为一步，全部步骤保存在 self.steps 供 gui.py 回放。
局部规则（逐格逐边）：
  R1 边界排除：朝棋盘外的开口不可能（外圈的 T 型、直线型由此直接确定）
  R2 确定格子推边：确定格子的开口方向 -> 需要连接，非开口方向 -> 墙
  R3 边推格子：边上的连接要求排除该格没有对应开口/有开口的形状
  R4 一致推边：未确定格子若剩余所有形状都（不）朝某方向开口 -> 该边定为（墙）需要连接
全局规则（最终解是一棵生成树：全连通、无环、恰 V-1 条连接）：
  R5 成环检查：确定连接边必须构成森林（并查集），围成闭环即矛盾
  R6 孤岛检查：把"需要连接∪未确定"的边洪泛，分成多块即矛盾
  R7 唯一出口：连通块通向外界的未确定边只剩一条 -> 该边必连
  R8 预算/容量：树需要恰 块数-1 条跨块边，恰好只剩这么多条时全部必连；
     块内确定边已满 c-1 条（内部已是树）-> 块内剩余未知边全是墙
"""
import hashlib
import re
import sys
from collections import Counter
from pathlib import Path

from get_puzzle import GLYPH, decode

DIRS = ("R", "U", "L", "D")          # 顺序对应位 1, 2, 4, 8
BIT = {"R": 1, "U": 2, "L": 4, "D": 8}
DELTA = {"R": (1, 0), "U": (0, -1), "L": (-1, 0), "D": (0, 1)}
OPP = {"R": "L", "L": "R", "U": "D", "D": "U"}
DIR_CN = {"R": "右", "U": "上", "L": "左", "D": "下"}
ARROW = {"R": "→", "U": "↑", "L": "←", "D": "↓"}


def rot(m: int) -> int:
    """每点一次水管 = 4 位左循环移位（游戏源码 shlr4）"""
    return ((m << 1) & 15) | (m >> 3)


def orbit(m: int) -> set:
    """一个管道掩码旋转出的全部不同形状（直线型 2 种，其余 4 种，十字 1 种）"""
    s, cur = set(), m & 15
    for _ in range(4):
        s.add(cur)
        cur = rot(cur)
    return s


def board_check(w: int, h: int, mask_at):
    """盘面校验（游戏规则）：mask_at(x, y) 返回该格当前掩码。
    无悬空开口，且全部管道连成一个组。返回 (ok, msg)。"""
    for y in range(h):
        for x in range(w):
            m = mask_at(x, y)
            for d in DIRS:
                if m & BIT[d]:
                    dx, dy = DELTA[d]
                    nx, ny = x + dx, y + dy
                    inside = 0 <= nx < w and 0 <= ny < h
                    if not inside or not mask_at(nx, ny) & BIT[OPP[d]]:
                        return False, f"格({x+1},{y+1}) {DIR_CN[d]}开口悬空"
    seen, stack = {(0, 0)}, [(0, 0)]
    while stack:
        x, y = stack.pop()
        m = mask_at(x, y)
        for d in DIRS:
            if m & BIT[d]:
                dx, dy = DELTA[d]
                n = (x + dx, y + dy)
                if 0 <= n[0] < w and 0 <= n[1] < h and n not in seen:
                    seen.add(n)
                    stack.append(n)
    if len(seen) != w * h:
        return False, f"只连通 {len(seen)}/{w * h} 格"
    return True, "无悬空开口且全部连通"


class Contradiction(Exception):
    """推理出矛盾（正常谜题不应发生，发生说明有 bug）"""


class Solver:
    def __init__(self, w: int, h: int, task: list):
        self.w, self.h, self.task = w, h, task
        self.task_hex = "".join(f"{v:x}" for row in task for v in row)
        self.poss = {(x, y): orbit(task[y][x])
                     for y in range(h) for x in range(w)}
        self.edges = {}                  # ("H"|"V", x, y) -> 1 / -1
        self.steps = []
        self.snapshot("初始", "读入题面：每格的可能性 = 该格管道旋转出的全部形状", [])

    # ---------- 基础工具 ----------

    def ekey(self, x, y, d):
        """格子 (x,y) 在 d 方向上的边键；棋盘外没有边（永远当墙）"""
        if d == "R":
            return ("H", x, y)
        if d == "L":
            return ("H", x - 1, y)
        if d == "U":
            return ("V", x, y - 1)
        return ("V", x, y)  # D

    def has_edge(self, x, y, d):
        dx, dy = DELTA[d]
        return 0 <= x + dx < self.w and 0 <= y + dy < self.h

    def edge_state(self, x, y, d):
        if not self.has_edge(x, y, d):
            return -1                    # 棋盘外一律是墙
        return self.edges.get(self.ekey(x, y, d), 0)

    def set_edge(self, x, y, d, state):
        k = self.ekey(x, y, d)
        old = self.edges.get(k, 0)
        if old != 0 and old != state:
            raise Contradiction(f"边 {k} 状态冲突: {old} vs {state}")
        self.edges[k] = state

    def snapshot(self, rule, desc, changed):
        self.steps.append({
            "rule": rule, "desc": desc, "changed": changed,
            "poss": {k: frozenset(v) for k, v in self.poss.items()},
            "edges": dict(self.edges),
        })

    @staticmethod
    def _state_text(s):
        if len(s) == 1:
            return f"该格确定为 {GLYPH[next(iter(s))]}"
        return f"剩{len(s)}种可能"

    # ---------- 推理规则（每次应用一处，记一步） ----------

    def step_border(self):
        """R1 边界排除"""
        for y in range(self.h):
            for x in range(self.w):
                walls = [d for d in DIRS if not self.has_edge(x, y, d)]
                if not walls:
                    continue
                old = self.poss[(x, y)]
                new = {m for m in old if not any(m & BIT[d] for d in walls)}
                if new == old:
                    continue
                if not new:
                    raise Contradiction(f"格({x+1},{y+1}) 无可能形状")
                where = "、".join(DIR_CN[d] + ARROW[d] for d in walls)
                self.poss[(x, y)] = new
                self.snapshot("R1 边界排除",
                              f"R1 边界: 格({x+1},{y+1}) 朝{where}是棋盘外 → "
                              f"{self._state_text(new)}",
                              [("cell", (x, y))])

    def step_r2(self):
        """R2 确定格子推边"""
        for (x, y), s in self.poss.items():
            if len(s) != 1:
                continue
            states = [self.edge_state(x, y, d) for d in DIRS]
            if 0 not in states:          # 四个方向的边都已定，无需再推
                continue
            m = next(iter(s))
            changed = [("cell", (x, y))]
            open_d = [d for d in DIRS if m & BIT[d]]
            wall_d = [d for d in DIRS if not m & BIT[d]]
            for d in open_d:
                if not self.has_edge(x, y, d):
                    raise Contradiction(f"格({x+1},{y+1}) 开口朝棋盘外")
                self.set_edge(x, y, d, 1)
                changed.append(("edge", self.ekey(x, y, d)))
            for d in wall_d:
                if self.has_edge(x, y, d):
                    self.set_edge(x, y, d, -1)
                    changed.append(("edge", self.ekey(x, y, d)))
            self.snapshot("R2 确定推边",
                          f"R2 确定格子({x+1},{y+1}) {GLYPH[m]}: "
                          f"{'、'.join(DIR_CN[d] for d in open_d)}需要连接，"
                          f"{'、'.join(DIR_CN[d] for d in wall_d)}是墙",
                          changed)
            return True
        return False

    def step_r3(self):
        """R3 边推格子"""
        for (x, y), s in self.poss.items():
            if len(s) == 1:
                continue
            for d in DIRS:
                st = self.edge_state(x, y, d)
                if st == 0:
                    continue
                want = st == 1
                new = {m for m in s if bool(m & BIT[d]) == want}
                if new == s:
                    continue
                if not new:
                    raise Contradiction(f"格({x+1},{y+1}) 无可能形状")
                self.poss[(x, y)] = new
                side = "需要连接" if want else "是墙"
                changed = [("cell", (x, y))]
                if self.has_edge(x, y, d):
                    changed.append(("edge", self.ekey(x, y, d)))
                self.snapshot("R3 边推格子",
                              f"R3 边推格子: 格({x+1},{y+1}) 的{DIR_CN[d]}"
                              f"{ARROW[d]}{side} → {self._state_text(new)}",
                              changed)
                return True
        return False

    def step_r4(self):
        """R4 一致推边"""
        for (x, y), s in self.poss.items():
            if len(s) == 1:
                continue
            for d in DIRS:
                if self.edge_state(x, y, d) != 0:
                    continue
                n_open = sum(1 for m in s if m & BIT[d])
                if n_open == len(s):
                    state, why = 1, f"都开口向{DIR_CN[d]}{ARROW[d]} → 该边需要连接"
                elif n_open == 0:
                    state, why = -1, f"都不开口向{DIR_CN[d]}{ARROW[d]} → 该边是墙"
                else:
                    continue
                self.set_edge(x, y, d, state)
                self.snapshot("R4 一致推边",
                              f"R4 一致推边: 格({x+1},{y+1}) 剩{len(s)}种形状{why}",
                              [("cell", (x, y)), ("edge", self.ekey(x, y, d))])
                return True
        return False

    # ---------- 全局规则（生成树性质：无环 + 全连通） ----------

    def _cells_of(self, key):
        """边键两端的格子"""
        o, x, y = key
        if o == "H":
            return (x, y), (x + 1, y)
        return (x, y), (x, y + 1)

    def _set_edge_key(self, key, state):
        o, x, y = key
        self.set_edge(x, y, "R" if o == "H" else "D", state)

    def step_global(self) -> bool:
        """一轮全局推理：R5/R6 查矛盾，R7/R8 推新边。
        发现矛盾抛 Contradiction（信息区分成环/孤岛）；应用了一条新边返回 True。"""
        # R5: 确定连接边建并查集，必须构成森林；顺便统计每块的大小与内部确定边数
        root = {(x, y): (x, y) for y in range(self.h) for x in range(self.w)}
        size = {(x, y): 1 for y in range(self.h) for x in range(self.w)}
        ecount = {(x, y): 0 for y in range(self.h) for x in range(self.w)}

        def find(a):
            while root[a] != a:
                root[a] = root[root[a]]
                a = root[a]
            return a

        for key, v in self.edges.items():
            if v != 1:
                continue
            a, b = self._cells_of(key)
            ra, rb = find(a), find(b)
            if ra == rb:
                (x1, y1), (x2, y2) = a, b
                raise Contradiction(
                    f"成环: 格({x1+1},{y1+1})与格({x2+1},{y2+1})之间的确定连接围成闭环")
            if size[ra] < size[rb]:
                ra, rb = rb, ra
            root[rb] = ra
            size[ra] += size[rb]
            ecount[ra] += ecount[rb] + 1
        k = sum(1 for c in root if find(c) == c)

        # R6: 把"未确定∪需要连接"的边洪泛，最终树的所有边都在这个图里，
        # 它不连通说明必然出现孤岛
        seen, comps = set(), []
        for y in range(self.h):
            for x in range(self.w):
                if (x, y) in seen:
                    continue
                comp, stack = {(x, y)}, [(x, y)]
                seen.add((x, y))
                while stack:
                    cx, cy = stack.pop()
                    for d in DIRS:
                        if self.has_edge(cx, cy, d) and \
                                self.edge_state(cx, cy, d) != -1:
                            dx, dy = DELTA[d]
                            n = (cx + dx, cy + dy)
                            if n not in seen:
                                seen.add(n)
                                comp.add(n)
                                stack.append(n)
                comps.append(comp)
        if len(comps) > 1:
            comps.sort(key=len)
            small = comps[0]
            sx, sy = next(iter(small))
            raise Contradiction(
                f"孤岛: {len(small)}格区域（如({sx+1},{sy+1})）与其余"
                f"{self.w * self.h - len(small)}格被墙隔死")

        # 未确定边分类：跨块（出口） / 块内
        cross, esc, internal = [], {}, {}
        for key in ([("H", x, y) for y in range(self.h) for x in range(self.w - 1)]
                    + [("V", x, y) for y in range(self.h - 1)
                       for x in range(self.w)]):
            if self.edges.get(key, 0) != 0:
                continue
            a, b = self._cells_of(key)
            ra, rb = find(a), find(b)
            if ra == rb:
                internal.setdefault(ra, []).append(key)
            else:
                cross.append(key)
                esc[ra] = esc.get(ra, 0) + 1
                esc[rb] = esc.get(rb, 0) + 1

        # R7: 某连通块只剩一个出口 -> 该边必连
        for r, n in esc.items():
            if n != 1:
                continue
            key = next(kk for kk in cross
                       if find(self._cells_of(kk)[0]) == r
                       or find(self._cells_of(kk)[1]) == r)
            a, b = self._cells_of(key)
            self._set_edge_key(key, 1)
            self.snapshot("R7 唯一出口",
                          f"R7 唯一出口: 格({a[0]+1},{a[1]+1})与格({b[0]+1},{b[1]+1})"
                          f"是其所在连通块唯一的出路 -> 该边需要连接",
                          [("edge", key)])
            return True

        # R8a: 跨块预算 —— 树需要恰 k-1 条跨块边；恰好只剩这么多条时全部必连
        need = k - 1
        if len(cross) < need:
            raise Contradiction(
                f"孤岛: {k}个连通块需要{need}条跨块连接，但只剩{len(cross)}条通路")
        if need > 0 and len(cross) == need:
            key = cross[0]
            a, b = self._cells_of(key)
            self._set_edge_key(key, 1)
            self.snapshot("R8 预算",
                          f"R8 预算: {k}个连通块恰好只剩{need}条跨块通路 -> 全部必连，"
                          f"先连格({a[0]+1},{a[1]+1})与格({b[0]+1},{b[1]+1})",
                          [("edge", key)])
            return True

        # R8b: 块内容量 —— 内部确定边已满 c-1 条（已是树），再多任何一条内部边都成环
        for r, keys in internal.items():
            c, e = size[r], ecount[r]
            if e != c - 1 or not keys:
                continue
            key = keys[0]
            a, b = self._cells_of(key)
            self._set_edge_key(key, -1)
            self.snapshot("R8 容量",
                          f"R8 容量: 格({a[0]+1},{a[1]+1})与格({b[0]+1},{b[1]+1})所在块"
                          f"（{c}格）内部已缝满{e}条连接 -> 该边是墙",
                          [("edge", key)])
            return True
        return False

    def propagate(self):
        """从当前状态继续推到不动：局部规则优先，然后全局规则，交替到稳定"""
        while True:
            if self.step_r2() or self.step_r3() or self.step_r4():
                continue
            if self.step_global():
                continue
            break

    def run(self):
        self.step_border()
        self.propagate()
        return self.steps

    # ---------- 结果 ----------

    def is_solved(self):
        return all(len(s) == 1 for s in self.poss.values())

    def mask(self, x, y):
        return next(iter(self.poss[(x, y)]))

    def undetermined(self):
        return [(x, y) for (x, y), s in self.poss.items() if len(s) != 1]

    def rotations(self):
        """每格最小旋转次数。与游戏官方校验串一致：直线型周期为 2，最小次数
        恰好就是官方的规范化取值（转2次记0、转3次记1）。"""
        out = []
        for y in range(self.h):
            for x in range(self.w):
                m0, cur = self.task[y][x], self.task[y][x]
                for k in range(4):
                    if cur == self.mask(x, y):
                        out.append(k)
                        break
                    cur = rot(cur)
        return out

    def verify_board(self):
        """盘面校验（游戏规则）：无悬空开口，且全部管道连成一个组。"""
        return board_check(self.w, self.h, self.mask)

    def md5_ok(self, hashed: str) -> bool:
        """游戏官方的胜利判定: md5(task + 旋转串) == hashedSolution"""
        if not hashed:
            return False
        sol = "".join(str(k) for k in self.rotations())
        return hashlib.md5((self.task_hex + sol).encode()).hexdigest() == hashed


# ---------- 命令行 ----------

def load_puzzle(path: str):
    """读取 get_puzzle.py 保存的谜题文件"""
    text = Path(path).read_text(encoding="utf-8")
    task_hex = re.search(r"task_hex: ([0-9a-f]+)", text).group(1)
    w, h = map(int, re.search(r"size: (\d+)x(\d+)", text).groups())
    hs = re.search(r"hashed_solution: ([0-9a-f]{32})", text)
    return w, h, task_hex, hs.group(1) if hs else ""


def newest_puzzle() -> str:
    files = sorted(Path(__file__).parent.glob("puzzles/*.txt"))
    if not files:
        sys.exit("puzzles/ 下没有谜题，先运行 python get_puzzle.py")
    return str(files[-1])


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else newest_puzzle()
    w, h, task_hex, hashed = load_puzzle(path)
    solver = Solver(w, h, decode(task_hex, w, h))
    try:
        solver.run()
    except Contradiction as e:
        sys.exit(f"推理矛盾: {e}")

    counts = Counter(s["rule"] for s in solver.steps if s["rule"] != "初始")
    summary = "、".join(f"{r.split()[0]}×{n}" for r, n in counts.items())
    print(f"谜题: {path}")
    print(f"推理步数: {len(solver.steps) - 1}（{summary}）")

    if solver.is_solved():
        print("\n最终盘面（全部格子都已确定）：")
        for y in range(h):
            print(" ".join(GLYPH[solver.mask(x, y)] for x in range(w)))
        ok, msg = solver.verify_board()
        print(f"\n盘面校验: {'✓' if ok else '✗'} {msg}")
        if hashed:
            print(f"官方 md5 校验: {'✓ 通过' if solver.md5_ok(hashed) else '✗ 不通过'}")
    else:
        stuck = solver.undetermined()
        print(f"\n推理卡住：还有 {len(stuck)} 格未确定（按要求不搜索不枚举）：")
        print("  " + "  ".join(f"({x+1},{y+1})" for x, y in stuck))
        print("\n当前盘面（？= 未确定）：")
        for y in range(h):
            print(" ".join(GLYPH[solver.mask(x, y)]
                           if len(solver.poss[(x, y)]) == 1 else "？"
                           for x in range(w)))


if __name__ == "__main__":
    main()
