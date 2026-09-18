"use strict";
/*
 * test_content.js —— 用最小 DOM 模拟跑 content.js 的盘面扫描与「一键求解」流程。
 * 校验：wrap 检测、格子解析、求解后向格子派发的点击次数是否把盘面转成解。
 * 运行：node test_content.js
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const { PipesSolver, rot4, boardCheck } = require("./solver.js");
function rotK(m, k) { let r = m & 15; for (let i = 0; i < (k & 3); i++) r = rot4(r); return r; }

/* ---------- 极简 DOM ---------- */
let ALL = [];                       // 所有已挂到文档的元素
function mkEl(tag) {
    const el = {
        tagName: (tag || "div").toUpperCase(),
        className: "", id: "", textContent: "",
        style: {}, children: [], parent: null,
        checked: false, disabled: false,
        _handlers: {}, _qs: {},
        classList: {
            add(c) { if (!el.className.split(/\s+/).includes(c)) el.className = (el.className + " " + c).trim(); },
            remove(c) { el.className = el.className.split(/\s+/).filter(x => x && x !== c).join(" "); },
            contains(c) { return el.className.split(/\s+/).includes(c); },
        },
        appendChild(c) { c.parent = el; el.children.push(c); if (!ALL.includes(c)) ALL.push(c); return c; },
        querySelector(sel) { return el._qs[sel] || null; },
        querySelectorAll() { return []; },
        addEventListener(t, fn) { (el._handlers[t] = el._handlers[t] || []).push(fn); },
        dispatchEvent(ev) { (el._handlers[ev.type] || []).forEach(fn => fn(ev)); return true; },
        getBoundingClientRect() { return { x: 0, y: 0, width: 10, height: 10 }; },
    };
    // innerHTML 赋值时把带 id="..." 的标签解析成子元素（够测试用）
    Object.defineProperty(el, "innerHTML", {
        get() { return el._html || ""; },
        set(html) {
            el._html = html; el.children = []; el._qs = {};
            const re = /<(\w+)([^>]*)>/g; let m;
            while ((m = re.exec(html))) {
                const tagName = m[1], attrs = m[2];
                const idm = /id="([\w-]+)"/.exec(attrs);
                const child = mkEl(tagName);
                if (idm) { child.id = idm[1]; el._qs["#" + idm[1]] = child; }
                if (/\bchecked\b/.test(attrs)) child.checked = true;
                if (/\bdisabled\b/.test(attrs)) child.disabled = true;
                el.appendChild(child);
            }
        },
    });
    return el;
}
function matches(el, sel) {
    // 支持测试用到的少量选择器：#id、.class、tag.class、逗号分隔
    return sel.split(",").some(part => {
        part = part.trim();
        if (part.startsWith("#")) return el.id === part.slice(1);
        if (part.startsWith(".")) return el.classList.contains(part.slice(1));
        const m = /^([a-zA-Z]+)\.([\w-]+)$/.exec(part);
        if (m) return el.tagName === m[1].toUpperCase() && el.classList.contains(m[2]);
        return el.tagName === part.toUpperCase();
    });
}
function descendants(root, out) { out = out || []; root.children.forEach(c => { out.push(c); descendants(c, out); }); return out; }

const document = {
    body: mkEl("body"),
    createElement: mkEl,
    addEventListener() {},
    contains(el) { return !!(el && (el === document.body || ALL.includes(el))); },
    querySelector(sel) {
        const parts = sel.split(",").map(s => s.trim());
        for (const p of parts) {
            // 支持 "A B"（后代）与 "#game .board-back > .cell"（直接子）
            if (p.includes(">")) {
                const [lhs, rhs] = p.split(">").map(s => s.trim());
                const parents = document.querySelectorAll(lhs);
                for (const par of parents)
                    for (const ch of par.children) if (matches(ch, rhs)) return ch;
                continue;
            }
            const toks = p.split(/\s+/);
            let pool = [document.body].concat(descendants(document.body));
            let found = null;
            const first = pool.filter(e => matches(e, toks[0]));
            for (const base of first) {
                if (toks.length === 1) { found = base; break; }
                const inside = descendants(base).filter(e => matches(e, toks[1]));
                if (inside.length) { found = inside[0]; break; }
            }
            if (found) return found;
        }
        return null;
    },
    querySelectorAll(sel) {
        let pool = [document.body].concat(descendants(document.body));
        const res = [];
        sel.split(",").map(s => s.trim()).forEach(p => {
            if (p.includes(">")) {
                const [lhs, rhs] = p.split(">").map(s => s.trim());
                const parents = document.querySelectorAll(lhs);
                parents.forEach(par => par.children.forEach(ch => { if (matches(ch, rhs) && !res.includes(ch)) res.push(ch); }));
                return;
            }
            const toks = p.split(/\s+/);
            if (toks.length === 1) { pool.forEach(e => { if (matches(e, toks[0]) && !res.includes(e)) res.push(e); }); return; }
            pool.forEach(e => {
                if (!matches(e, toks[0])) return;
                descendants(e).forEach(d => { if (matches(d, toks[1]) && !res.includes(d)) res.push(d); });
            });
        });
        return res;
    },
};

const timers = [];
const window = { document, event: null };
const ctx = {
    window, document, console,
    MouseEvent: function (type, init) { return Object.assign({ type }, init); },
    setTimeout: (fn) => { timers.push(fn); return timers.length; },
    clearTimeout: () => {},
    setInterval: (fn) => { timers.push(fn); return timers.length; },
    clearInterval: () => {},
    Array, Math, Date, Set, Map, Promise, Error, JSON, Object, String, Number, parseInt, parseFloat, isNaN,
};
ctx.window.window = window;
ctx.globalThis = ctx;

/* ---------- 造一个 wrap 棋盘 DOM ---------- */
function taskFromFixture(file) {
    const text = fs.readFileSync(file, "utf8");
    const th = /task_hex: ([0-9a-f]+)/.exec(text)[1];
    const [, w, h] = /size: (\d+)x(\d+)/.exec(text);
    const W = +w, H = +h, task = [];
    for (let y = 0; y < H; y++) { task.push([]); for (let x = 0; x < W; x++) task[y].push(parseInt(th[y * W + x], 16)); }
    return { task, w: W, h: H };
}

function buildBoard(task, w, h, wrap, statuses) {
    const game = mkEl("div"); game.id = "game";
    const back = mkEl("div"); back.className = "board-back";
    game.appendChild(back); document.body.appendChild(game);
    const clickCount = new Map();
    const cellsByXY = new Map();
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
        const cell = mkEl("div");
        cell._task = task[y][x];
        cell.className = "cell pipe" + task[y][x];
        const st = (statuses && statuses[x + "," + y]) || 0;
        if (st) cell.className += " cell-" + st;
        cell.style.top = (y * 30) + "px"; cell.style.left = (x * 30) + "px";
        cell._handlers.click = [(ev) => {
            const cur = cell._status || 0;
            // 真实游戏：普通点击 −1 mod 4，Ctrl+点击 +1 mod 4
            cell._status = ev && ev.ctrlKey ? (cur + 1) % 4 : (cur + 3) % 4;
            clickCount.set(x + "," + y, (clickCount.get(x + "," + y) || 0) + 1);
            cell.className = cell.className.replace(/\s*cell-\d/g, "") +
                (cell._status ? " cell-" + cell._status : "");
        }];
        cell._status = st;
        cellsByXY.set(x + "," + y, cell);
        back.appendChild(cell);
    }
    if (wrap) {
        ["wrapH", "wrapV"].forEach(cls => {
            const m = mkEl("div"); m.className = cls; back.appendChild(m);
        });
    }
    return { clickCount, cellsByXY };
}

function run(fixture, wrap, statuses) {
    const { task, w, h } = taskFromFixture(fixture);
    ALL = []; document.body = mkEl("body");
    window.__pipesHelperLoaded = false;          // 允许在同一上下文里重新加载 content.js
    timers.length = 0;
    const { clickCount, cellsByXY } = buildBoard(task, w, h, wrap, statuses || null);

    const src = fs.readFileSync(path.join(__dirname, "content.js"), "utf8");
    // 扩展里 solver.js 与 content.js 同处一个隔离世界；这里放进同一 vm 上下文
    const solverSrc = fs.readFileSync(path.join(__dirname, "solver.js"), "utf8");
    vm.runInNewContext(solverSrc, ctx, { filename: "solver.js" });
    vm.runInNewContext(src, ctx, { filename: "content.js" });

    // 触发 waitBoard 的 interval 回调，启用按钮
    timers.splice(0).forEach(fn => fn());
    const solveBtn = document.querySelector("#pl-solve");
    if (!solveBtn) throw new Error("未找到 pl-solve 按钮");

    // 点击「一键求解」，await 其内部 promise 链（用一批 microtask/timeout 轮询）
    return new Promise((resolve, reject) => {
        solveBtn.dispatchEvent({ type: "click" });
        let spins = 0;
        (function pump() {
            const pending = timers.splice(0);
            pending.forEach(fn => fn());
            if (++spins > 20000) return reject(new Error("timeout"));
            // 判断完成：状态文本含「搜索求解完成」或「未求出」
            const st = document.querySelector("#pl-status");
            if (st && /搜索求解完成|未求出完整解|求解出错/.test(st.textContent)) return resolve({ st, clickCount, cellsByXY, task, w, h, wrap });
            setImmediate(pump);
        })();
    });
}

(async () => {
    const fixtures = [
        ["../puzzles/pipes_10x10_wrap_id1813890_s13_20260918_232718.txt", true],
        ["../puzzles/pipes_4x4_wrap_id2217103_s10_20260918_232720.txt", true],
        ["../puzzles/pipes_10x10_id6672132_20260912_005605.txt", false],
    ];
    let pass = 0;
    for (const [f, wrap] of fixtures) {
        const file = path.join(__dirname, f);
        const r = await run(file, wrap);
        const solved = /搜索求解完成/.test(r.st.textContent);
        // 校验点击后的真实盘面：每格掩码 = rot4^status(题面)，应满足无悬空+全连通
        const masks = new Map();
        r.cellsByXY.forEach((cell, k) => masks.set(k, rotK(cell._task, cell._status || 0)));
        const chk = boardCheck(r.w, r.h, (x, y) => masks.get(x + "," + y), r.wrap);
        const ok = solved && chk.ok;
        console.log(`${path.basename(file).padEnd(52)} wrap=${wrap ? 1 : 0} ` +
            `状态=${solved ? "完成" : "失败"} 摆好后的盘面校验=${chk.ok ? "✓" : "✗ " + chk.msg}`);
        if (ok) pass++;
    }

    // 失败路径：故意把一个格子摆错，应报「求解出错」而不是卡住/静默
    const badFile = path.join(__dirname, fixtures[2][0]);
    const pz = taskFromFixture(badFile);
    let wrongStatus = 0;
    for (let st = 1; st <= 3; st++) {          // 找一个会推出矛盾的错摆
        const probe = new PipesSolver(pz.w, pz.h, pz.task, false);
        try { probe.assume(0, 0, rotK(pz.task[0][0], st)); probe.run(); }
        catch (e) { wrongStatus = st; break; }
    }
    if (!wrongStatus) { console.log("（本题未找到可制造矛盾的错摆，跳过失败路径用例）"); }
    else {
        const r = await run(badFile, false, { "0,0": wrongStatus });
        const handled = /求解出错|未求出完整解/.test(r.st.textContent);
        console.log(`${"错摆(0,0)失败路径".padEnd(52)} 状态=${handled ? "已妥善报错" : "未处理"}`);
        if (handled) pass++;
    }

    const total = fixtures.length + (wrongStatus ? 1 : 0);
    console.log(`\n通过 ${pass}/${total}`);
    process.exit(pass === total ? 0 : 1);
})().catch(e => { console.error("FAIL", e); process.exit(1); });
