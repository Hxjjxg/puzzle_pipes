# -*- coding: utf-8 -*-
"""图形界面：回放求解器从第 0 步开始的每一次调整。

用进度条（滑块）拖到任意一步，或用 上一步/下一步/自动播放（也可用键盘 ←/→/空格）。
颜色含义：
  蓝色粗管道   = 已确定的格子          浅蓝底 = 已确定
  灰色细管道   = 未确定格子剩余可能形状的开口并集（右下角数字 = 剩余可能数）
  绿色连接块   = 这条边确定需要连接    红色 × = 这条边确定是墙
  黄色高亮     = 这一步发生变化的格子/边
用法: python gui.py [puzzles/xxx.txt]        （默认取 puzzles/ 里最新一道）
      python gui.py --selftest              无窗口渲染全部步骤做自检
"""
import sys
import tkinter as tk
from pathlib import Path

from get_puzzle import decode
from solver import BIT, DELTA, DIRS, Solver, load_puzzle, newest_puzzle

CELL = 52           # 每格像素
PAD = 16            # 棋盘边距
PIPE = "#1565c0"    # 已确定管道
GUESS = "#b8b8b8"   # 未确定的可能开口
CONN = "#2e7d32"    # 需要连接的边
WALL = "#c62828"    # 墙
MARK = "#f9a825"    # 本步变化高亮
GRID = "#dddddd"
FONT = ("Microsoft YaHei", 10)
FONT_S = ("Microsoft YaHei", 8)


class ReplayApp:
    def __init__(self, root, title, steps, w, h, task):
        self.root, self.steps, self.w, self.h, self.task = root, steps, w, h, task
        self.idx = 0
        self.playing = False
        self.total_edges = (w - 1) * h + w * (h - 1)

        root.title(title)
        self.status = tk.Label(root, font=FONT, anchor="w", justify="left",
                               wraplength=PAD * 2 + w * CELL)
        self.status.pack(fill="x", padx=PAD, pady=(8, 0))
        self.canvas = tk.Canvas(root, width=PAD * 2 + w * CELL,
                                height=PAD * 2 + h * CELL, bg="white",
                                highlightthickness=0)
        self.canvas.pack(padx=PAD, pady=6)

        bar = tk.Frame(root)
        bar.pack(fill="x", padx=PAD)
        tk.Button(bar, text="◀ 上一条", width=9, font=FONT,
                  command=lambda: self.go(self.idx - 1)).pack(side="left")
        self.play_btn = tk.Button(bar, text="▶ 自动播放", width=10, font=FONT,
                                  command=self.toggle_play)
        self.play_btn.pack(side="left", padx=8)
        tk.Button(bar, text="下一条 ▶", width=9, font=FONT,
                  command=lambda: self.go(self.idx + 1)).pack(side="left")

        self.slider = tk.Scale(root, from_=0, to=len(steps) - 1, orient="horizontal",
                               showvalue=False, command=self.on_slide,
                               length=PAD * 2 + w * CELL)
        self.slider.pack(fill="x", padx=PAD, pady=(2, 10))

        for key, fn in (("<Left>", lambda e: self.go(self.idx - 1)),
                        ("<Right>", lambda e: self.go(self.idx + 1)),
                        ("<space>", lambda e: self.toggle_play())):
            root.bind(key, fn)

        self.draw(0)

    # ---------- 控件回调 ----------

    def on_slide(self, v):
        self.draw(int(v))

    def go(self, i):
        self.slider.set(max(0, min(len(self.steps) - 1, i)))

    def toggle_play(self):
        self.playing = not self.playing
        self.play_btn.config(text="⏸ 暂停" if self.playing else "▶ 自动播放")
        if self.playing:
            self.root.after(250, self.tick)

    def tick(self):
        if not self.playing:
            return
        if self.idx >= len(self.steps) - 1:
            self.toggle_play()
            return
        self.go(self.idx + 1)
        self.root.after(250, self.tick)

    # ---------- 绘制 ----------

    def draw_pipe(self, cx, cy, mask, color, width):
        cv, r = self.canvas, CELL // 2 - 5
        for d in DIRS:
            if mask & BIT[d]:
                dx, dy = DELTA[d]
                cv.create_line(cx, cy, cx + dx * r, cy + dy * r,
                               fill=color, width=width, capstyle="round")

    def draw_edge(self, key, state, highlight):
        cv = self.canvas
        o, x, y = key
        if o == "H":                     # (x,y)-(x+1,y) 之间的竖直分界
            bx = PAD + (x + 1) * CELL
            cy = PAD + y * CELL + CELL // 2
            if state == 1:
                if highlight:
                    cv.create_line(bx - 10, cy, bx + 10, cy, fill=MARK,
                                   width=9, capstyle="round")
                cv.create_line(bx - 8, cy, bx + 8, cy, fill=CONN,
                               width=4, capstyle="round")
            else:
                s = 5
                if highlight:
                    cv.create_oval(bx - s - 3, cy - s - 3, bx + s + 3, cy + s + 3,
                                   outline=MARK, width=3)
                cv.create_line(bx - s, cy - s, bx + s, cy + s, fill=WALL, width=3)
                cv.create_line(bx - s, cy + s, bx + s, cy - s, fill=WALL, width=3)
        else:                            # (x,y)-(x,y+1) 之间的水平分界
            by = PAD + (y + 1) * CELL
            cx = PAD + x * CELL + CELL // 2
            if state == 1:
                if highlight:
                    cv.create_line(cx, by - 10, cx, by + 10, fill=MARK,
                                   width=9, capstyle="round")
                cv.create_line(cx, by - 8, cx, by + 8, fill=CONN,
                               width=4, capstyle="round")
            else:
                s = 5
                if highlight:
                    cv.create_oval(cx - s - 3, by - s - 3, cx + s + 3, by + s + 3,
                                   outline=MARK, width=3)
                cv.create_line(cx - s, by - s, cx + s, by + s, fill=WALL, width=3)
                cv.create_line(cx - s, by + s, cx + s, by - s, fill=WALL, width=3)

    def draw(self, i):
        self.idx = i
        st = self.steps[i]
        cv, w, h = self.canvas, self.w, self.h
        cv.delete("all")

        # 网格线
        for gy in range(h + 1):
            cv.create_line(PAD, PAD + gy * CELL, PAD + w * CELL, PAD + gy * CELL,
                           fill=GRID)
        for gx in range(w + 1):
            cv.create_line(PAD + gx * CELL, PAD, PAD + gx * CELL, PAD + h * CELL,
                           fill=GRID)

        # 边的连接状态
        hi_edges = {k for t, k in st["changed"] if t == "edge"}
        for key, v in st["edges"].items():
            self.draw_edge(key, v, key in hi_edges)

        # 格子
        for (x, y), s in st["poss"].items():
            px, py = PAD + x * CELL, PAD + y * CELL
            cx, cy = px + CELL // 2, py + CELL // 2
            if len(s) == 1:
                cv.create_rectangle(px + 1, py + 1, px + CELL - 1, py + CELL - 1,
                                    fill="#e8f1fb", outline="")
                self.draw_pipe(cx, cy, next(iter(s)), PIPE, 4)
            else:
                union = 0
                for m in s:
                    union |= m
                self.draw_pipe(cx, cy, union, GUESS, 2)
                cv.create_text(px + CELL - 4, py + CELL - 3, text=str(len(s)),
                               fill="#9e9e9e", font=FONT_S, anchor="se")
            cv.create_text(px + 4, py + 3, text=f"{self.task[y][x]:x}",
                           fill="#c0c8d0", font=FONT_S, anchor="nw")

        # 本步变化的格子高亮
        for t, v in st["changed"]:
            if t == "cell":
                x, y = v
                cv.create_rectangle(PAD + x * CELL + 1, PAD + y * CELL + 1,
                                    PAD + (x + 1) * CELL - 1,
                                    PAD + (y + 1) * CELL - 1,
                                    outline=MARK, width=3)

        # 状态文字
        det = sum(1 for s in st["poss"].values() if len(s) == 1)
        nconn = sum(1 for v in st["edges"].values() if v == 1)
        nwall = sum(1 for v in st["edges"].values() if v == -1)
        line1 = f"第 {i}/{len(self.steps) - 1} 步  [{st['rule']}]  {st['desc']}"
        line2 = (f"确定格子 {det}/{w * h} · 需要连接的边 {nconn} · 墙 {nwall} · "
                 f"未定边 {self.total_edges - nconn - nwall}")
        self.status.config(text=line1 + "\n" + line2)


def selftest(steps, w, h, task):
    root = tk.Tk()
    root.withdraw()
    app = ReplayApp(root, "selftest", steps, w, h, task)
    for i in range(len(steps)):
        app.draw(i)
        root.update()
    root.destroy()
    print(f"gui selftest ok: {len(steps)} 步全部渲染成功")


def main():
    args = [a for a in sys.argv[1:] if a != "--selftest"]
    path = args[0] if args else newest_puzzle()
    w, h, task_hex, _ = load_puzzle(path)
    task = decode(task_hex, w, h)
    solver = Solver(w, h, task)
    solver.run()
    title = f"求解回放 · {Path(path).name} · 共 {len(solver.steps) - 1} 步"
    if "--selftest" in sys.argv:
        selftest(solver.steps, w, h, task)
        return
    root = tk.Tk()
    ReplayApp(root, title, solver.steps, w, h, task)
    root.mainloop()


if __name__ == "__main__":
    main()
