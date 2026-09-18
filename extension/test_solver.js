"use strict";
/*
 * test_solver.js —— solver.js 的离线对拍/回归测试（node 运行）。
 * 读取 puzzles/*.txt，按 wrap 标志求解并用官方 md5 校验（md5(task_hex+旋转串)）。
 *   node test_solver.js            跑 puzzles/ 下全部题面
 *   node test_solver.js a.txt b.txt [--no-search]   只测指定文件 / 跳过搜索
 */
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const { PipesSolver } = require("./solver.js");

function loadPuzzle(file) {
    const text = fs.readFileSync(file, "utf8");
    const taskHex = /task_hex: ([0-9a-f]+)/.exec(text)[1];
    const [, w, h] = /size: (\d+)x(\d+)/.exec(text);
    const hs = /hashed_solution: ([0-9a-f]{32})/.exec(text);
    const wrap = /wrap: ([01])/.exec(text);
    const W = +w, H = +h, task = [];
    for (let y = 0; y < H; y++) {
        task.push([]);
        for (let x = 0; x < W; x++) task[y].push(parseInt(taskHex[y * W + x], 16));
    }
    return { w: W, h: H, task, taskHex, hashed: hs ? hs[1] : "", wrap: !!(wrap && wrap[1] === "1") };
}

function md5(s) { return crypto.createHash("md5").update(s).digest("hex"); }
function rotTimes(mask, k) { let m = mask & 15; while (k-- > 0) m = ((m << 1) & 15) | (m >> 3); return m; }

function run(file, doSearch) {
    const pz = loadPuzzle(file);
    const s = new PipesSolver(pz.w, pz.h, pz.task, pz.wrap);
    let ok = true, stats = null;
    if (doSearch) {
        stats = s.search({ strategy: "mrv" });
        ok = stats.solved;
    } else {
        s.run();
        ok = s.isSolved();
    }
    let md5ok = null;
    if (ok && pz.hashed) {
        const rot = s.rotations().join("");
        md5ok = md5(pz.taskHex + rot) === pz.hashed;
    }
    const name = path.basename(file);
    let detail = ok ? "解出" : "未解出";
    if (stats) detail += ` nodes=${stats.nodes} backtracks=${stats.contradictions}`;
    console.log(`${name.padEnd(54)} wrap=${pz.wrap ? 1 : 0} ${detail} md5=${md5ok === null ? "-" : (md5ok ? "✓" : "✗")}`);
    return ok && md5ok !== false;
}

const args = process.argv.slice(2);
const doSearch = !args.includes("--no-search");
const files = args.filter(a => !a.startsWith("--"));
const list = files.length ? files
    : fs.readdirSync(path.join(__dirname, "..", "puzzles"))
        .filter(f => f.endsWith(".txt"))
        .map(f => path.join(__dirname, "..", "puzzles", f))
        .sort();

let pass = 0;
for (const f of list) if (run(f, doSearch)) pass++;
console.log(`\n通过 ${pass}/${list.length}`);
process.exit(pass === list.length ? 0 : 1);
