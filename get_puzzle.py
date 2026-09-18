# -*- coding: utf-8 -*-
"""从 puzzle-pipes.com 抓取 Pipes（接水管）谜题并保存。

页面 HTML 里自带全部题面数据，无需浏览器渲染：
  var task = '...';               十六进制串，每个字符 = 一个格子的 4-bit 管道掩码
  puzzleWidth: W, puzzleHeight: H 盘面尺寸
  wrap: 0/1                        是否环形（torus）模式
  <span id="puzzleID">6,813,781</span>  题号（可在 specific.php 输入重现同一题）

掩码含义（位值）: 1=右  2=上  4=左  8=下
用法:
  python get_puzzle.py [size]        随机出一道题, size 对应主站下拉框（默认 3 = 10x10）
  python get_puzzle.py [size] [id]   按题号抓取指定题目
                                     注意: 题号在对应尺寸下才有效
  python get_puzzle.py wrap [size]   抓对应尺寸的 Wrap（环形）题；size 可写 "10x10"、
                                     位数序号或省略（默认 10x10 wrap）
输出: puzzles/ 下每个谜题一个 txt 文件（文件名带尺寸、题号与抓取时间）
"""
import re
import sys
import datetime
import urllib.request
import urllib.parse
from pathlib import Path

URL = "https://www.puzzle-pipes.com/"
OUT_DIR = Path(__file__).parent / "puzzles"
PROXY = "http://127.0.0.1:7892"
_opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
)

# 主站下拉框的 size 参数 -> (边长, 是否 wrap)
# 普通尺寸 0..6 对应 4/5/7/10/15/20/25；Wrap 尺寸 = 普通尺寸 + 10。
# 另：7/8/9 = Special Daily/Weekly/Monthly，17/18/19 = 它们的 Wrap 版（尺寸由服务器决定）。
SIZE_MAP = {
    0: (4, False), 1: (5, False), 2: (7, False), 3: (10, False),
    4: (15, False), 5: (20, False), 6: (25, False),
    10: (4, True), 11: (5, True), 12: (7, True), 13: (10, True),
    14: (15, True), 15: (20, True), 16: (25, True),
    7: (None, False), 8: (None, False), 9: (None, False),
    17: (None, True), 18: (None, True), 19: (None, True),
}
SIDES = (4, 5, 7, 10, 15, 20, 25)

# 管道掩码 -> 形状字符（字符笔画的方向 = 开口/连通方向）。
# 掩码位含义已对照游戏源码确认: dc=[1,0,-1,0], dr=[0,-1,0,1]
#   1=右  2=上  4=左  8=下
GLYPH = {
    0b0000: "·",
    0b0001: "╶", 0b0010: "╵", 0b0100: "╴", 0b1000: "╷",
    0b0011: "└", 0b0110: "┘", 0b1100: "┐", 0b1001: "┌",
    0b0101: "─", 0b1010: "│",
    0b0111: "┴", 0b1110: "┤", 0b1101: "┬", 0b1011: "├",
    0b1111: "┼",
}


def parse_size(token, as_side=False) -> int:
    """把用户写的尺寸解析成主站 size 参数。

    规则（避免歧义）：
      * 纯数字默认 = 主站下拉框序号（0..19，含 Special/Wrap），保持旧约定；
        ``as_side=True`` 时（如 "wrap 5"）把纯数字当边长；
      * 含 "x" 的写法（如 "10x10"）= 边长，wrap 由后缀/开关决定；
      * 后缀 "-wrap"/"wrap"/"环形" 表示环形；只有 "wrap" 一个词时默认 10x10 wrap。
    例: "3"->10x10, "13"->10x10wrap, "10x10"->10x10, "10x10-wrap"->10x10wrap,
        "wrap 15"->15x15wrap, "wrap"->10x10wrap。"""
    raw = str(token).strip().lower()
    if raw in {"wrap", "环形", "torus"}:
        return size_for(10, True)        # 只写 wrap -> 默认 10x10 wrap
    wrap = False
    for suffix in ("-wrap", "wrap", "环形"):
        if raw.endswith(suffix) and raw != suffix:
            wrap = True
            raw = raw[: -len(suffix)]
    raw = raw.strip()
    if not raw:                          # 空串也当默认 10x10 wrap
        return size_for(10, True)
    if "x" in raw:                       # 边长写法，如 10x10
        side = int(raw.split("x")[0])
        if side not in SIDES:
            raise SystemExit(f"不支持的边长 {side}，可选 {SIDES}")
        return size_for(side, wrap)
    num = int(raw)
    if as_side and num in SIDES:
        return size_for(num, wrap)
    if as_side:
        raise SystemExit(f"不支持的边长 {num}，可选 {SIDES}")
    if num in SIDES and wrap:
        # "5-wrap" 这类，纯数字当边长
        return size_for(num, wrap)
    if num not in SIZE_MAP:              # 纯数字 -> 主站序号
        raise SystemExit(f"不支持的尺寸序号 {num}，普通 0-9 / wrap 10-19；"
                         f"或用边长写法如 10x10、10x10-wrap")
    return num


def size_for(side: int, wrap: bool) -> int:
    """按边长 + wrap 标志取主站 size 参数（4/5/7/10/15/20/25）。"""
    base = SIDES.index(side)
    return base + (10 if wrap else 0)


def _open(req, timeout: int = 30) -> str:
    """先直连请求，失败再走本地代理"""
    try:
        return urllib.request.urlopen(req, timeout=timeout).read().decode(
            "utf-8", "replace")
    except OSError:
        return _opener.open(req, timeout=timeout).read().decode(
            "utf-8", "replace")


def fetch_puzzle(size: int, puzzle_id: str | None = None):
    if puzzle_id:
        # 按题号请求（specific.php 的表单就是 POST 这些字段到主页）
        data = urllib.parse.urlencode(
            {"specific": "1", "specid": puzzle_id, "size": size}).encode()
        req = urllib.request.Request(URL, data=data,
                                     headers={"User-Agent": "Mozilla/5.0"})
    else:
        req = urllib.request.Request(f"{URL}?size={size}",
                                     headers={"User-Agent": "Mozilla/5.0"})
    html = _open(req)

    task = re.search(r"var task = '([0-9a-f]+)'", html)
    dims = re.search(r"puzzleWidth: (\d+), puzzleHeight: (\d+)", html)
    pid = re.search(r'id="puzzleID">([\d,]+)<', html)
    hs = re.search(r"hashedSolution: '([0-9a-f]{32})'", html)
    wrap = re.search(r"wrap:(\d)", html)
    if not task or not dims or not pid:
        raise RuntimeError("页面中未找到谜题数据（题号可能不存在）")
    return (task.group(1), int(dims.group(1)), int(dims.group(2)),
            pid.group(1), hs.group(1) if hs else "",
            bool(wrap and wrap.group(1) == "1"))


def decode(task_hex: str, w: int, h: int):
    """十六进制串 -> 行优先的位掩码矩阵"""
    assert len(task_hex) == w * h, f"task 长度 {len(task_hex)} 与 {w}x{h} 不符"
    vals = [int(c, 16) for c in task_hex]
    return [vals[r * w:(r + 1) * w] for r in range(h)]


def render(grid):
    return "\n".join(" ".join(GLYPH[v] for v in row) for row in grid)


def fetch_and_save(size: int, puzzle_id: str | None = None) -> Path:
    """抓取一道谜题并保存到 puzzles/，返回文件路径"""
    task_hex, w, h, pid, hashed, wrap = fetch_puzzle(size, puzzle_id)
    grid = decode(task_hex, w, h)

    OUT_DIR.mkdir(exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = "_wrap" if wrap else ""
    out = OUT_DIR / f"pipes_{w}x{h}{suffix}_id{pid.replace(',', '')}_s{size}_{ts}.txt"
    out.write_text(
        f"source: {URL}?size={size}\n"
        f"id: {pid}\n"
        f"fetched: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n"
        f"size: {w}x{h}\n"
        f"wrap: {1 if wrap else 0}\n"
        f"task_hex: {task_hex}\n"
        f"hashed_solution: {hashed}\n"
        f"mask: 1=right 2=up 4=left 8=down (hex digit per cell, row-major)\n\n"
        f"{render(grid)}\n",
        encoding="utf-8",
    )
    print(f"已保存 {out}  (题号: {pid}{'，wrap 环形' if wrap else ''})")
    print(render(grid))
    return out


def main():
    args = sys.argv[1:]
    wrap_flag = "wrap" in [a.lower() for a in args]
    args = [a for a in args if a.lower() != "wrap"]
    if not args:
        size = size_for(10, True) if wrap_flag else 3
    elif wrap_flag:
        # "wrap 15" 这类：把数字当边长，再转成对应的 wrap 序号
        size = parse_size(args[0], as_side=True)
        if size < 10:
            size += 10
    else:
        size = parse_size(args[0])
    pid = args[1].replace(",", "") if len(args) > 1 else None
    fetch_and_save(size, pid)


if __name__ == "__main__":
    main()
