# -*- coding: utf-8 -*-
"""从 puzzle-pipes.com 抓取 Pipes（接水管）谜题并保存。

页面 HTML 里自带全部题面数据，无需浏览器渲染：
  var task = '...';               十六进制串，每个字符 = 一个格子的 4-bit 管道掩码
  puzzleWidth: W, puzzleHeight: H 盘面尺寸
  <span id="puzzleID">6,813,781</span>  题号（可在 specific.php 输入重现同一题）

掩码含义（位值）: 1=右  2=上  4=左  8=下
用法:
  python get_puzzle.py [size]        随机出一道题, size 默认 3 (10x10)
  python get_puzzle.py [size] [id]   按题号抓取指定题目
输出: puzzles/ 下每个谜题一个 txt 文件
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
    if not task or not dims or not pid:
        raise RuntimeError("页面中未找到谜题数据（题号可能不存在）")
    return (task.group(1), int(dims.group(1)), int(dims.group(2)),
            pid.group(1), hs.group(1) if hs else "")


def decode(task_hex: str, w: int, h: int):
    """十六进制串 -> 行优先的位掩码矩阵"""
    assert len(task_hex) == w * h, f"task 长度 {len(task_hex)} 与 {w}x{h} 不符"
    vals = [int(c, 16) for c in task_hex]
    return [vals[r * w:(r + 1) * w] for r in range(h)]


def render(grid):
    return "\n".join(" ".join(GLYPH[v] for v in row) for row in grid)


def main():
    size = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    pid = sys.argv[2].replace(",", "") if len(sys.argv) > 2 else None
    task_hex, w, h, pid, hashed = fetch_puzzle(size, pid)
    grid = decode(task_hex, w, h)

    OUT_DIR.mkdir(exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = OUT_DIR / f"pipes_{w}x{h}_id{pid.replace(',', '')}_{ts}.txt"
    out.write_text(
        f"source: {URL}?size={size}\n"
        f"id: {pid}\n"
        f"fetched: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n"
        f"size: {w}x{h}\n"
        f"task_hex: {task_hex}\n"
        f"hashed_solution: {hashed}\n"
        f"mask: 1=right 2=up 4=left 8=down (hex digit per cell, row-major)\n\n"
        f"{render(grid)}\n",
        encoding="utf-8",
    )
    print(f"已保存 {out}  (题号: {pid})")
    print(render(grid))


if __name__ == "__main__":
    main()
