# -*- coding: utf-8 -*-
"""wrap（环形）求解的回归测试。

覆盖：
1. 环形几何：一整行横管在 wrap 下应判连通（无悬空），非 wrap 下应判悬空；
2. 真实 wrap 题面用 DFS 搜索解出后，官方 md5 通过、盘面校验通过、
   恰有 V-1 条连接边且无环（生成树性质）；
3. wrap 专属 R9：某行横边仅剩一条未定、其余全是连接时，该边必须是墙。

用 `python test_wrap.py` 运行（无需测试框架）。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from get_puzzle import decode
from solver import Solver, board_check, load_puzzle


def test_torus_geometry():
    """4x4 每格十字（15）：环面上四周相接、无悬空且全连通；
    非 wrap 时外圈开口朝棋盘外，应判悬空。这直接检验了 wrap 没有边界墙。"""
    w = h = 4
    mask_at = lambda x, y: 0b1111            # ┼
    ok_wrap, msg_wrap = board_check(w, h, mask_at, wrap=True)
    assert ok_wrap, f"wrap 下十字盘面应连通: {msg_wrap}"
    ok_flat, msg_flat = board_check(w, h, mask_at, wrap=False)
    assert not ok_flat, "非 wrap 下外圈十字应因朝外悬空而失败"
    # 反例：整盘横管在环面上是 4 个独立的行环，不应判全连通。
    rows = board_check(w, h, lambda x, y: 0b0101, wrap=True)
    assert not rows[0], "4 个行环各自独立，不应判全连通"
    print("ok: 环形几何（十字盘面 wrap 连通 / 非 wrap 悬空；行环不连通）")


def test_r9_breaks_row_ring():
    """把某行横边除一条外全部设为连接，R9 应把剩下那条定为墙。"""
    w = h = 4
    s = Solver(w, h, [[5] * w for _ in range(h)], wrap=True)
    for x in range(w - 1):
        s.set_edge(x, 0, "R", 1)              # 第 0 行前三条横边连接
    assert s.edges.get(("H", w - 1, 0), 0) == 0
    assert s.step_global(), "R9 应推出一条新边"
    assert s.edges[("H", w - 1, 0)] == -1, "整圈只剩一条未定 -> 该边必是墙"
    print("ok: R9 环必须断开")


def test_wrap_puzzle_tree():
    """真实 wrap 题面：搜索求解 + 官方 md5 + 生成树性质。"""
    files = sorted(Path(__file__).parent.glob("puzzles/*wrap*.txt"))
    assert files, "缺少 wrap 题面 fixture"
    for path in files:
        w, h, task_hex, hashed, wrap = load_puzzle(str(path))
        assert wrap, f"{path.name} 应标记为 wrap"
        s = Solver(w, h, decode(task_hex, w, h), wrap=True)
        assert s.search("mrv"), f"{path.name} 搜索未解出"
        ok, msg = s.verify_board()
        assert ok, f"{path.name} 盘面校验失败: {msg}"
        if hashed:
            assert s.md5_ok(hashed), f"{path.name} 官方 md5 不通过"

        # 连接边必须构成生成树：V-1 条、无环、全连通。
        parent = {(x, y): (x, y) for y in range(h) for x in range(w)}

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        used = 0
        for key, v in s.edges.items():
            if v != 1:
                continue
            used += 1
            o, x, y = key
            a = (x, y)
            b = ((x + 1) % w, y) if o == "H" else (x, (y + 1) % h)
            ra, rb = find(a), find(b)
            assert ra != rb, f"{path.name} 连接边成环: {key}"
            parent[rb] = ra
        assert used == w * h - 1, \
            f"{path.name} 连接边数 {used} != V-1 = {w * h - 1}"
        roots = {find((x, y)) for y in range(h) for x in range(w)}
        assert len(roots) == 1, f"{path.name} 未全连通"
        print(f"ok: {path.name} 解出（md5 {'✓' if hashed else '—'}，"
              f"{used}=V-1 条边且无环）")


if __name__ == "__main__":
    test_torus_geometry()
    test_r9_breaks_row_ring()
    test_wrap_puzzle_tree()
    print("test_wrap ok: 环形几何 + R9 + 真实 wrap 题面生成树校验全部通过")
