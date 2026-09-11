# -*- coding: utf-8 -*-
"""还原 puzzle-pipes.com 的游戏本身。

玩法与原版一致：点击（或按住拖过）水管使它逆时针转 90°（源码 shlr4），
把所有管道连成一个组、没有开口悬空/朝外即解开。
与中心连通的格子会显示浅绿底色（对应原版的连通高亮）。

用法: python game.py [puzzles/xxx.txt]
      不带参数则联网随机取一题（失败时退回本地最新谜题）
      python game.py --selftest   无窗口自检
"""
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from get_puzzle import decode, fetch_puzzle
from solver import BIT, DELTA, DIRS, OPP, board_check, load_puzzle, newest_puzzle, rot

CELL = 56
PAD = 16
PIPE = "#1565c0"      # 管道
WIN_PIPE = "#2e7d32"  # 解开后的管道
CONN_BG = "#d9ead3"   # 与中心连通的格子底色
GRID = "#cccccc"
FONT = ("Microsoft YaHei", 11)


class GameApp:
    def __init__(self, root, w, h, task, info):
        self.root, self.w, self.h, self.info = root, w, h, info
        self.task = task
        self.reset_state()
        self.won = False
        self.drag_cells = set()

        root.title("接水管 · 还原版")
        self.status = tk.Label(root, font=FONT, anchor="w")
        self.status.pack(fill="x", padx=PAD, pady=(8, 4))
        self.canvas = tk.Canvas(root, width=PAD * 2 + w * CELL,
                                height=PAD * 2 + h * CELL, bg="white",
                                highlightthickness=0)
        self.canvas.pack(padx=PAD)
        bar = tk.Frame(root)
        bar.pack(fill="x", padx=PAD, pady=8)
        tk.Button(bar, text="重新开始", font=FONT, command=self.reset).pack(side="left")
        tk.Button(bar, text="换一题（联网）", font=FONT,
                  command=self.new_puzzle).pack(side="left", padx=8)

        self.canvas.bind("<Button-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", lambda e: self.drag_cells.clear())

        self.draw()
        self.check()

    # ---------- 状态 ----------

    def reset_state(self):
        self.mask = {(x, y): self.task[y][x]
                     for y in range(self.h) for x in range(self.w)}
        self.clicks = 0

    def reset(self):
        self.reset_state()
        self.won = False
        self.draw()
        self.check()

    def new_puzzle(self):
        try:
            task_hex, w, h, pid, _ = fetch_puzzle(3)
        except OSError as e:
            messagebox.showerror("抓取失败", f"联网取题失败：{e}")
            return
        self.w, self.h, self.info = w, h, f"题号 {pid}"
        self.task = decode(task_hex, w, h)
        self.reset_state()
        self.won = False
        self.canvas.config(width=PAD * 2 + w * CELL, height=PAD * 2 + h * CELL)
        self.draw()
        self.check()

    # ---------- 交互 ----------

    def cell_at(self, ex, ey):
        x, y = int((ex - PAD) // CELL), int((ey - PAD) // CELL)
        return (x, y) if 0 <= x < self.w and 0 <= y < self.h else None

    def on_press(self, e):
        cell = self.cell_at(e.x, e.y)
        if cell:
            self.drag_cells = {cell}
            self.rotate(*cell)

    def on_drag(self, e):
        cell = self.cell_at(e.x, e.y)
        if cell and cell not in self.drag_cells:
            self.drag_cells.add(cell)
            self.rotate(*cell)

    def rotate(self, x, y):
        if self.won:
            return
        self.mask[(x, y)] = rot(self.mask[(x, y)])   # 逆时针 90°，同原版
        self.clicks += 1
        self.draw()
        self.check()

    # ---------- 判定与绘制 ----------

    def component(self):
        """与中心格互相连通的格子集合（原版即从中心泛洪）"""
        start = (self.w // 2, self.h // 2)
        seen, stack = {start}, [start]
        while stack:
            x, y = stack.pop()
            m = self.mask[(x, y)]
            for d in DIRS:
                if m & BIT[d]:
                    dx, dy = DELTA[d]
                    n = (x + dx, y + dy)
                    if 0 <= n[0] < self.w and 0 <= n[1] < self.h \
                            and n not in seen and self.mask[n] & BIT[OPP[d]]:
                        seen.add(n)
                        stack.append(n)
        return seen

    def check(self):
        ok, msg = board_check(self.w, self.h, lambda x, y: self.mask[(x, y)])
        if ok:
            self.won = True
            self.status.config(
                text=f"✓ 解开了！共旋转 {self.clicks} 次 · {self.info}")
        else:
            self.status.config(
                text=f"已连通 {len(self.component())}/{self.w * self.h} 格 · {msg} · "
                     f"{self.info}")

    def draw(self):
        cv, w, h = self.canvas, self.w, self.h
        cv.delete("all")
        comp = self.component()
        color = WIN_PIPE if self.won else PIPE

        for y in range(h):
            for x in range(w):
                if (x, y) in comp:
                    px, py = PAD + x * CELL, PAD + y * CELL
                    cv.create_rectangle(px + 1, py + 1, px + CELL - 1,
                                        py + CELL - 1, fill=CONN_BG, outline="")
        for gy in range(h + 1):
            cv.create_line(PAD, PAD + gy * CELL, PAD + w * CELL, PAD + gy * CELL,
                           fill=GRID)
        for gx in range(w + 1):
            cv.create_line(PAD + gx * CELL, PAD, PAD + gx * CELL, PAD + h * CELL,
                           fill=GRID)
        r = CELL // 2 - 6
        for y in range(h):
            for x in range(w):
                cx, cy = PAD + x * CELL + CELL // 2, PAD + y * CELL + CELL // 2
                for d in DIRS:
                    if self.mask[(x, y)] & BIT[d]:
                        dx, dy = DELTA[d]
                        cv.create_line(cx, cy, cx + dx * r, cy + dy * r,
                                       fill=color, width=5, capstyle="round")


def selftest():
    # board_check 断言：2x2 闭环应判解开；全是直线必有悬空
    loop = {(0, 0): 1 | 8, (1, 0): 4 | 8, (0, 1): 1 | 2, (1, 1): 4 | 2}
    ok, msg = board_check(2, 2, lambda x, y: loop[(x, y)])
    assert ok, msg
    ok2, _ = board_check(2, 2, lambda x, y: 5)
    assert not ok2
    # 交互冒烟：加载本地谜题，模拟旋转与重开
    root = tk.Tk()
    root.withdraw()
    w, h, task_hex, _ = load_puzzle(newest_puzzle())
    app = GameApp(root, w, h, decode(task_hex, w, h), "selftest")
    for x, y in [(0, 0), (1, 1), (2, 3), (2, 3)]:
        app.rotate(x, y)
        root.update()
    app.reset()
    root.update()
    assert app.clicks == 0 and not app.won
    root.destroy()
    print("game selftest ok: board_check 断言 + 旋转/重开 冒烟通过")


def main():
    if "--selftest" in sys.argv:
        selftest()
        return
    args = [a for a in sys.argv[1:]]
    if args:
        w, h, task_hex, _ = load_puzzle(args[0])
        task, info = decode(task_hex, w, h), Path(args[0]).name
    else:
        try:
            task_hex, w, h, pid, _ = fetch_puzzle(3)
            task, info = decode(task_hex, w, h), f"题号 {pid}"
        except OSError:
            p = newest_puzzle()
            w, h, task_hex, _ = load_puzzle(p)
            task, info = decode(task_hex, w, h), Path(p).name + "（离线）"
    root = tk.Tk()
    GameApp(root, w, h, task, info)
    root.mainloop()


if __name__ == "__main__":
    main()
