# -*- coding: utf-8 -*-
"""图形界面：回放求解器从第 0 步开始的每一次调整，并支持手动操作。

回放：用进度条（滑块）拖到任意一步，或用 上一步/下一步/自动播放（键盘 ←/→/空格）。
手动操作（作用于最新状态，操作后自动跳到最后一步）：
  左键点格子 = 挑选该格的一个候选形状；再点 = 换下一个候选（循环）。
  右键点格子 = 撤销该格的手动选择（它引发的所有后续推理一并回退）。
  「自动推理」勾选框（默认开）：
    开 = 挑选后 R1-R4/R5-R8 推理自动继续到不动；
    关 = 挑选只记录、不推理，方便自己逐格手推观察；
    此时可用「执行推理」按钮随时手动推一轮（若推出矛盾，
    自动回退到推理前的状态并提示成环/孤岛等原因）。
  「撤销全部手动」按钮 = 回到纯推理状态。
  若某次挑选推出矛盾：自动回滚；若尝试时不存在任何人工假设，
  则该形状被确定排除（记作「手动排除」步，同样合法）。
  矛盾信息会说明原因：局部冲突 / 成环（R5）/ 孤岛（R6、R8）。
  挑选后的自动推理包含全局规则 R5-R8（见 solver.py），比纯局部规则强得多。

颜色含义：
  蓝色粗管道 = 已确定的格子（浅蓝底）；橙色框 = 存在手动假设的格子
  灰色字形   = 未确定格子剩余的候选形状（格子左上角小字 = 题面掩码值）
  绿色连接块 = 这条边确定需要连接；红色 × = 这条边确定是墙
  黄色高亮   = 当前这一步发生变化的格子/边
用法: python gui.py [puzzles/xxx.txt]        （默认取 puzzles/ 里最新一道）
      python gui.py 6672132                 按题号加载（默认 10x10；本地已有直接用，
                                            否则联网抓取并保存到 puzzles/）
      python gui.py 5 6180259               尺寸+题号（题号在对应尺寸下才有效）
      python gui.py --selftest              无窗口渲染全部步骤 + 手动操作自检
"""
import sys
import tkinter as tk
from pathlib import Path

from get_puzzle import GLYPH, decode, fetch_and_save
from solver import BIT, DELTA, DIRS, Contradiction, Solver, load_puzzle, newest_puzzle

CELL = 52           # 每格像素
PAD = 16            # 棋盘边距
PIPE = "#1565c0"    # 已确定管道
CAND = "#5c6b7a"    # 未确定格子的候选形状字形
CONN = "#2e7d32"    # 需要连接的边
WALL = "#c62828"    # 墙
MARK = "#f9a825"    # 本步变化高亮
ASSUME = "#ef6c00"  # 手动假设的格子
GRID = "#dddddd"
FONT = ("Microsoft YaHei", 10)
FONT_S = ("Microsoft YaHei", 8)
FONT_CAND = ("Microsoft YaHei", 11)


class ReplayApp:
    def __init__(self, root, title, solver, hashed=""):
        self.root = root
        self.solver = solver
        self.hashed = hashed
        self.w, self.h = solver.w, solver.h
        self.total_edges = (self.w - 1) * self.h + self.w * (self.h - 1)
        self.manual_cands = {}    # 格子 -> 第一次手动挑选时冻结的候选形状列表
        self.manual_stack = []    # [(格子, 所选形状, 步骤检查点)]，LIFO 回退
        self.notice = ""          # 需要提示用户的信息（一次性）
        self.auto = tk.BooleanVar(value=True)   # 挑选后是否自动继续规则推理
        self.idx = 0
        self.playing = False

        root.title(title)
        self.status = tk.Label(root, font=FONT, anchor="w", justify="left",
                               wraplength=PAD * 2 + self.w * CELL)
        self.status.pack(fill="x", padx=PAD, pady=(8, 0))
        self.canvas = tk.Canvas(root, width=PAD * 2 + self.w * CELL,
                                height=PAD * 2 + self.h * CELL, bg="white",
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
        tk.Checkbutton(bar, text="自动推理", variable=self.auto,
                       font=FONT).pack(side="left", padx=(12, 0))
        tk.Button(bar, text="撤销全部手动", width=12, font=FONT,
                  command=self.revert_all).pack(side="right")
        tk.Button(bar, text="执行推理", width=9, font=FONT,
                  command=self.run_reason).pack(side="right", padx=8)

        self.slider = tk.Scale(root, from_=0, to=len(solver.steps) - 1,
                               orient="horizontal", showvalue=False,
                               command=self.on_slide,
                               length=PAD * 2 + self.w * CELL)
        self.slider.pack(fill="x", padx=PAD, pady=(2, 10))

        self.canvas.bind("<Button-1>", self.on_pick)
        self.canvas.bind("<Button-3>", self.on_revert)
        for key, fn in (("<Left>", lambda e: self.go(self.idx - 1)),
                        ("<Right>", lambda e: self.go(self.idx + 1)),
                        ("<space>", lambda e: self.toggle_play())):
            root.bind(key, fn)

        self.draw(0)

    # ---------- 回放控制 ----------

    def on_slide(self, v):
        self.draw(int(v))

    def go(self, i):
        self.slider.set(max(0, min(len(self.solver.steps) - 1, i)))

    def toggle_play(self):
        self.playing = not self.playing
        self.play_btn.config(text="⏸ 暂停" if self.playing else "▶ 自动播放")
        if self.playing:
            self.root.after(250, self.tick)

    def tick(self):
        if not self.playing:
            return
        if self.idx >= len(self.solver.steps) - 1:
            self.toggle_play()
            return
        self.go(self.idx + 1)
        self.root.after(250, self.tick)

    # ---------- 手动操作 ----------

    def cell_at(self, ex, ey):
        x, y = int((ex - PAD) // CELL), int((ey - PAD) // CELL)
        return (x, y) if 0 <= x < self.w and 0 <= y < self.h else None

    def on_pick(self, e):
        self.manual_pick(self.cell_at(e.x, e.y))

    def on_revert(self, e):
        self.manual_revert(self.cell_at(e.x, e.y))

    def propagate(self):
        self.solver.propagate()   # 局部规则 R2-R4 + 全局规则 R5-R8

    def unwind(self, cell):
        """LIFO 撤销手动挑选及其引发的全部推理步；cell=None 撤销全部"""
        while self.manual_stack:
            c, _pick, ckpt = self.manual_stack.pop()
            del self.solver.steps[ckpt:]
            snap = self.solver.steps[ckpt - 1]
            self.solver.poss = {k: set(v) for k, v in snap["poss"].items()}
            self.solver.edges = dict(snap["edges"])
            if cell is None or c == cell:
                break

    def manual_pick(self, cell):
        if cell is None:
            return
        x, y = cell
        sv = self.solver
        entry = next((t for t in self.manual_stack if t[0] == cell), None)
        prev = None
        if entry:                        # 已有手动挑选：先撤销，再换下一个候选
            prev = entry[1]
            self.unwind(cell)
        if len(sv.poss[cell]) == 1:
            self.notice = f"格({x+1},{y+1}) 已确定，不能手动挑选（右键可撤销手动挑选）"
            self.refresh()
            return
        self.manual_cands.setdefault(cell, sorted(sv.poss[cell]))
        cands = [m for m in self.manual_cands[cell] if m in sv.poss[cell]]
        if not cands:
            self.notice = f"格({x+1},{y+1}) 已无候选形状"
            self.refresh()
            return
        idx = 0 if prev is None else (cands.index(prev) + 1) % len(cands)
        pick = cands[idx]
        pristine = not self.manual_stack   # 尝试时是否不存在任何人工假设
        ckpt = len(sv.steps)
        sv.poss[cell] = {pick}
        sv.snapshot("手动挑选",
                    f"手动挑选: 格({x+1},{y+1}) = {GLYPH[pick]}"
                    f"（{len(cands)} 个候选中的第 {idx+1} 个）",
                    [("cell", cell)])
        self.manual_stack.append((cell, pick, ckpt))
        self.notice = ""
        if self.auto.get():
            try:
                self.propagate()
            except Contradiction as e:
                self.unwind(cell)              # 回滚这次挑选
                sv.poss[cell].discard(pick)
                if pristine:
                    self.manual_cands[cell] = [m for m in self.manual_cands[cell]
                                               if m != pick]
                    tag = "，该形状被排除"
                else:
                    tag = "（存在人工假设，仅回滚不排除）"
                sv.snapshot("手动排除",
                            f"手动挑选 格({x+1},{y+1})={GLYPH[pick]} 推出矛盾"
                            f"（{e}）{tag}",
                            [("cell", cell)])
                if pristine and sv.poss[cell]:
                    try:
                        self.propagate()
                    except Contradiction as e:
                        self.notice = f"排除后的状态自身矛盾（{e}），谜题数据异常？"
        self.refresh()

    def manual_revert(self, cell):
        if cell is None or not any(c == cell for c, _, _ in self.manual_stack):
            return
        self.unwind(cell)
        self.notice = ""
        self.refresh()

    def revert_all(self):
        if self.manual_stack:
            self.unwind(None)
            self.notice = ""
            self.refresh()

    def run_reason(self):
        """「执行推理」按钮：手动推一轮到不动（自动推理关闭时用）。
        若推出矛盾，回退到推理前的状态并提示原因。"""
        sv = self.solver
        ckpt = len(sv.steps)
        self.notice = ""
        try:
            self.propagate()
        except Contradiction as e:
            del sv.steps[ckpt:]
            snap = sv.steps[ckpt - 1]
            sv.poss = {k: set(v) for k, v in snap["poss"].items()}
            sv.edges = dict(snap["edges"])
            self.notice = f"推理矛盾（{e}），已回退到推理前；请检查或撤销手动选择"
        self.refresh()

    def refresh(self):
        self.slider.config(to=len(self.solver.steps) - 1)
        self.slider.set(len(self.solver.steps) - 1)
        self.draw(len(self.solver.steps) - 1)

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
        st = self.solver.steps[i]
        cv, w, h = self.canvas, self.w, self.h
        cv.delete("all")

        for gy in range(h + 1):
            cv.create_line(PAD, PAD + gy * CELL, PAD + w * CELL, PAD + gy * CELL,
                           fill=GRID)
        for gx in range(w + 1):
            cv.create_line(PAD + gx * CELL, PAD, PAD + gx * CELL, PAD + h * CELL,
                           fill=GRID)

        hi_edges = {k for t, k in st["changed"] if t == "edge"}
        for key, v in st["edges"].items():
            self.draw_edge(key, v, key in hi_edges)

        assumed = {c for c, _p, _k in self.manual_stack}
        for (x, y), s in st["poss"].items():
            px, py = PAD + x * CELL, PAD + y * CELL
            cx, cy = px + CELL // 2, py + CELL // 2
            if len(s) == 1:
                cv.create_rectangle(px + 1, py + 1, px + CELL - 1, py + CELL - 1,
                                    fill="#e8f1fb", outline="")
                self.draw_pipe(cx, cy, next(iter(s)), PIPE, 4)
            else:                        # 未确定：把剩余候选形状的字形画在格子里
                glyphs = "".join(GLYPH[m] for m in sorted(s))
                rows = "\n".join(glyphs[i:i + 2] for i in range(0, len(glyphs), 2))
                cv.create_text(cx, cy, text=rows, fill=CAND, font=FONT_CAND)
            cv.create_text(px + 4, py + 3, text=f"{self.solver.task[y][x]:x}",
                           fill="#9aa7b0", font=FONT_S, anchor="nw")
            if (x, y) in assumed:
                cv.create_rectangle(px + 1, py + 1, px + CELL - 1, py + CELL - 1,
                                    outline=ASSUME, width=3)

        for t, v in st["changed"]:
            if t == "cell":
                x, y = v
                cv.create_rectangle(PAD + x * CELL + 1, PAD + y * CELL + 1,
                                    PAD + (x + 1) * CELL - 1,
                                    PAD + (y + 1) * CELL - 1,
                                    outline=MARK, width=3)

        det = sum(1 for s in st["poss"].values() if len(s) == 1)
        nconn = sum(1 for v in st["edges"].values() if v == 1)
        nwall = sum(1 for v in st["edges"].values() if v == -1)
        line1 = f"第 {i}/{len(self.solver.steps) - 1} 步  [{st['rule']}]  {st['desc']}"
        line2 = (f"确定格子 {det}/{w * h} · 需要连接的边 {nconn} · 墙 {nwall} · "
                 f"未定边 {self.total_edges - nconn - nwall}")
        if det == w * h and self.hashed:
            line2 += " · 官方md5 " + ("✓" if self.solver.md5_ok(self.hashed) else "✗")
        if self.notice:
            line2 += "\n⚠ " + self.notice
        self.status.config(text=line1 + "\n" + line2)


def selftest(solver, hashed):
    root = tk.Tk()
    root.withdraw()
    app = ReplayApp(root, "selftest", solver, hashed)
    for i in range(len(solver.steps)):
        app.draw(i)
        root.update()
    stuck = solver.undetermined()
    if stuck:
        cell = stuck[0]

        # 自动推理关闭：挑选只记录不推理；执行推理遇矛盾回退到推理前
        app.auto.set(False)
        base = len(solver.steps)
        app.manual_pick(cell)            # 记录挑选，不推理
        assert len(solver.steps) == base + 1, "关闭自动推理后挑选只应记录一步"
        app.manual_pick(cell)            # 轮换到下一个候选（此题必为错误值）
        assert len(solver.steps) == base + 1, "轮换应先撤销再记录，仍只有一步"
        app.run_reason()                 # 手动推理 -> 矛盾 -> 回退
        assert len(solver.steps) == base + 1, "矛盾后应回退到挑选后"
        assert "矛盾" in app.notice
        app.revert_all()
        assert not app.manual_stack

        # 自动推理开启：挑选后传播继续，轮换触发「手动排除」
        app.auto.set(True)
        app.manual_pick(cell)            # 挑选
        app.manual_pick(cell)            # 轮换
        app.manual_pick(cell)            # 再轮换
        app.manual_revert(cell)          # 右键撤销
        app.revert_all()                 # 全部撤销
        assert not app.manual_stack

        # 关掉自动推理，手动点一格候选，「执行推理」收尾
        if solver.undetermined():
            app.auto.set(False)
            app.manual_pick(solver.undetermined()[0])
            app.run_reason()
            app.auto.set(True)

        assert all(solver.poss.values()), "poss 不应为空"
        for i in range(len(solver.steps)):
            app.draw(i)
            root.update()
    root.destroy()
    print(f"gui selftest ok: 渲染 {len(solver.steps)} 步 + 挑选/轮换/撤销/自动推理开关 冒烟通过")


def resolve_path(args):
    """命令行参数 -> 谜题文件路径。
    无参数 = puzzles/ 里最新一道；纯数字 = 题号（可带尺寸前缀，默认尺寸 3，
    本地已有该题号则直接用，否则联网抓取并保存）；其他 = 谜题文件路径。"""
    if not args:
        return Path(newest_puzzle())
    nums = [a.replace(",", "") for a in args]
    if nums[-1].isdigit():
        size = int(nums[0]) if len(nums) == 2 and nums[0].isdigit() else 3
        pid = nums[-1]
        saved = (sorted(Path(__file__).parent.glob(
                     f"puzzles/*_id{pid}_s{size}_*.txt"))
                 or sorted(Path(__file__).parent.glob(f"puzzles/*_id{pid}_*.txt")))
        if saved:
            return saved[-1]
        return fetch_and_save(size, pid)
    path = Path(args[0])
    if not path.exists():
        raise SystemExit(f"找不到谜题文件: {path}（也可只给题号，"
                         f"如 python gui.py 6672132）")
    return path


def main():
    args = [a for a in sys.argv[1:] if a != "--selftest"]
    try:
        path = resolve_path(args)
    except OSError as e:
        raise SystemExit(f"联网抓取题号失败: {e}")
    w, h, task_hex, hashed = load_puzzle(path)
    solver = Solver(w, h, decode(task_hex, w, h))
    solver.run()
    title = (f"求解回放 · {Path(path).name} · 共 {len(solver.steps) - 1} 步"
             f"（左键挑选/轮换候选形状，右键撤销手动）")
    if "--selftest" in sys.argv:
        selftest(solver, hashed)
        return
    root = tk.Tk()
    ReplayApp(root, title, solver, hashed)
    root.mainloop()


if __name__ == "__main__":
    main()
