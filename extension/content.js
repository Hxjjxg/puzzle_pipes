"use strict";
/*
 * content.js —— puzzle-pipes.com 的规则推理助手（内容脚本，隔离环境，只碰 DOM）。
 *
 * 盘面读取（不依赖页面内部变量）：
 *   每格 div.cell 的 class 里 pipe{N} = 题面掩码（永不改变），
 *   cell-{N} = 当前旋转状态（普通点击 -1 mod 4，Ctrl+点击 +1 mod 4），
 *   当前掩码 = shlr4(题面掩码, 状态)。位置由内联 top/left 换算成行列。
 *
 * 交互模型（与 gui.py 一致）：
 *   - 打开「自动推理」：立刻在后台做一轮 R1–R8 规则推理，出错（成环/孤岛）或
 *     推不下去就停；有结论时把建议旋转的格子闪烁高亮，等用户点击「确认填充」。
 *   - 确认后按当前盘面状态计算增量点击数逐格旋转（不擦掉用户已摆的格子：
 *     状态≠0 的格子一律当作人工假设，永远不会被改写），然后自动继续下一轮。
 *   - 关闭「自动推理」：什么都不做。
 *   - 「后退」：有建议时取消建议；否则撤销上一次填充（整批还原）。
 */
(function () {
    if (window.__pipesHelperLoaded) return;
    window.__pipesHelperLoaded = true;

    // ---------- 小工具 ----------
    var sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };

    function rotTimes(mask, times) {
        var m = mask & 15;
        for (var i = 0; i < (times & 3); i++) m = ((m << 1) & 15) | (m >> 3);
        return m;
    }

    /* 从当前状态转到目标掩码所需的最少点击；优先用 Ctrl+点击（反方向） */
    function minClicks(taskMask, status, targetMask) {
        var plain = 99, ctrl = 99, k, c;
        for (k = 0; k < 4; k++) {
            if (rotTimes(taskMask, k) !== targetMask) continue;
            c = (status - k + 8) % 4; if (c < plain) plain = c;
            c = (k - status + 8) % 4; if (c < ctrl) ctrl = c;
        }
        return ctrl < plain ? { n: ctrl, ctrl: true } : { n: plain, ctrl: false };
    }

    // ---------- 盘面扫描 ----------
    function scanBoard() {
        var els = Array.prototype.slice.call(
            document.querySelectorAll("#game .board-back > .cell"));
        els = els.filter(function (el) { return !el.classList.contains("wraptile"); });
        if (!els.length) return { ok: false, why: "未找到棋盘" };
        if (document.querySelector(".wraptile")) return { ok: false, why: "wrap（环形穿墙）模式暂不支持" };

        var cells = els.map(function (el) {
            var mPipe = el.className.match(/pipe(\d+)/);
            var mCell = el.className.match(/(?:^|\s)cell-([0-3])(?=\s|$)/);
            return {
                el: el,
                task: mPipe ? parseInt(mPipe[1], 10) : -1,
                status: mCell ? parseInt(mCell[1], 10) : 0,
                top: parseFloat(el.style.top), left: parseFloat(el.style.left),
            };
        });
        var xs = [], ys = [], i, j;
        cells.forEach(function (c) {
            if (xs.indexOf(c.left) < 0) xs.push(c.left);
            if (ys.indexOf(c.top) < 0) ys.push(c.top);
        });
        xs.sort(function (a, b) { return a - b; });
        ys.sort(function (a, b) { return a - b; });
        var w = xs.length, h = ys.length, task = [];
        for (i = 0; i < h; i++) { task.push([]); for (j = 0; j < w; j++) task[i].push(-1); }
        for (i = 0; i < cells.length; i++) {
            var c = cells[i];
            c.x = xs.indexOf(c.left); c.y = ys.indexOf(c.top);
            if (c.task < 0 || c.x < 0 || c.y < 0) return { ok: false, why: "棋盘解析失败" };
            task[c.y][c.x] = c.task;
        }
        for (i = 0; i < h; i++) for (j = 0; j < w; j++)
            if (task[i][j] < 0) return { ok: false, why: "棋盘不完整" };
        return {
            ok: true, w: w, h: h, task: task, cells: cells,
            key: w + "x" + h + ":" + cells.map(function (c) { return c.task; }).join(""),
        };
    }

    function readStatus(el) {
        var m = el.className.match(/(?:^|\s)cell-([0-3])(?=\s|$)/);
        return m ? parseInt(m[1], 10) : 0;
    }

    function fireClick(el, ctrl) {
        var r = el.getBoundingClientRect();
        var init = {
            bubbles: true, cancelable: true, view: window,
            button: 0, buttons: 1, clientX: r.x + r.width / 2, clientY: r.y + r.height / 2,
            ctrlKey: !!ctrl,
        };
        el.dispatchEvent(new MouseEvent("mousedown", init));
        el.dispatchEvent(new MouseEvent("mouseup", init));
        el.dispatchEvent(new MouseEvent("click", init));
    }

    // ---------- 面板 ----------
    var panel, statusEl, mainBtn, backBtn, autoChk, fillChk;
    var flashCls = "pl-suggest", fillCls = "pl-fill", errCls = "pl-error";
    var auto = false, proposals = null, history = [], busy = false, lastBoardKey = null;
    var autoFilled = new Set();          // 扩展自动填充过的格子（蓝色可开关显示）
    var fillShow = true;

    function setStatus(text) { if (statusEl) statusEl.textContent = text; }

    function clearFlash() {
        document.querySelectorAll("." + flashCls).forEach(function (el) {
            el.classList.remove(flashCls);
        });
    }

    function clearErrorMarks() {
        document.querySelectorAll("." + errCls).forEach(function (el) {
            el.classList.remove(errCls);
        });
    }

    function refreshFillMarks() {
        document.querySelectorAll("." + fillCls).forEach(function (el) {
            el.classList.remove(fillCls);
        });
        if (!fillShow) return;
        autoFilled.forEach(function (el) {
            if (document.contains(el)) el.classList.add(fillCls);
        });
    }

    function updateButtons() {
        if (busy) {
            mainBtn.disabled = true; mainBtn.textContent = "填充中…";
        } else if (proposals && proposals.length) {
            mainBtn.disabled = false; mainBtn.textContent = "确认填充 " + proposals.length + " 格";
        } else {
            mainBtn.disabled = false; mainBtn.textContent = "重新推理";
        }
        backBtn.disabled = busy;
    }

    function dropProposals(msg) {
        proposals = null;
        clearFlash();
        if (msg) setStatus(msg);
        updateButtons();
    }

    function runRound() {
        if (busy) return;
        dropProposals();
        clearErrorMarks();
        var scan = scanBoard();
        if (!scan.ok) { setStatus(scan.why); updateButtons(); return; }
        if (scan.key !== lastBoardKey) {          // 换题/重开：清空后退历史与填充标记
            history = []; lastBoardKey = scan.key;
            autoFilled.clear(); refreshFillMarks();
        }
        var elOf = {};
        scan.cells.forEach(function (c) { elOf[c.x + "," + c.y] = c.el; });

        var solver = new PipesSolver(scan.w, scan.h, scan.task);
        var i, c;
        try {
            for (i = 0; i < scan.cells.length; i++) {
                c = scan.cells[i];
                if (c.status !== 0)               // 用户已摆的格子 = 人工假设
                    solver.assume(c.x, c.y, rotTimes(c.task, c.status));
            }
            solver.run();
        } catch (e) {
            // 从推理开始到出错涉及过的所有格子标红
            var nErr = 0;
            solver.touched.forEach(function (key) {
                var el = elOf[key];
                if (el) { el.classList.add(errCls); nErr++; }
            });
            setStatus("推理出错，已停止：" + e.message +
                "\n红色标出从推理开始到出错涉及的 " + nErr + " 格（含手工摆放）");
            updateButtons();
            return;
        }

        var props = [], determined = 0;
        for (i = 0; i < scan.cells.length; i++) {
            c = scan.cells[i];
            var m = solver.maskAt(c.x, c.y);
            if (m === undefined) continue;
            determined++;
            var mc = minClicks(c.task, c.status, m);
            if (mc.n > 0)
                props.push({ x: c.x, y: c.y, el: c.el, target: m, clicks: mc.n, ctrl: mc.ctrl });
        }

        if (props.length) {
            proposals = props;
            props.forEach(function (p) { p.el.classList.add(flashCls); });
            setStatus("已确定 " + determined + "/" + (scan.w * scan.h) +
                " 格；建议旋转 " + props.length + " 格（橙色常亮）\n点击「确认填充」应用");
        } else {
            var total = scan.w * scan.h;
            if (determined === total) {
                var chk = boardCheck(scan.w, scan.h, function (x, y) {
                    return solver.maskAt(x, y);
                });
                setStatus("已确定 " + total + "/" + total + " 格\n盘面校验：" +
                    (chk.ok ? "✓ " : "✗ ") + chk.msg);
            } else {
                setStatus("已确定 " + determined + "/" + total +
                    " 格；推理卡住，剩 " + (total - determined) +
                    " 格（不搜索不枚举）\n可手动摆放后再「重新推理」");
            }
        }
        updateButtons();
    }

    async function applyProposals() {
        if (!proposals || !proposals.length || busy) return;
        busy = true; updateButtons();
        var batch = [], list = proposals;
        for (var i = 0; i < list.length; i++) {
            var p = list[i], el = p.el;
            if (!document.contains(el)) continue;
            // 确认前用户可能又动过这格：按当前状态重算点击（目标掩码不变）
            var mPipe = el.className.match(/pipe(\d+)/);
            var taskMask = mPipe ? parseInt(mPipe[1], 10) : 0;
            var mc = minClicks(taskMask, readStatus(el), p.target);
            var before = readStatus(el);
            for (var n = 0; n < mc.n; n++) { fireClick(el, mc.ctrl); await sleep(25); }
            var after = readStatus(el);
            if (after !== before) batch.push({ x: p.x, y: p.y, before: before, after: after, el: el });
        }
        history.push(batch);
        busy = false;
        proposals = null; clearFlash();
        batch.forEach(function (b) { autoFilled.add(b.el); });
        refreshFillMarks();
        setStatus(batch.length
            ? "已填充 " + batch.length + " 格（蓝色标出），继续推理…"
            : "建议的格子已被摆到位，无需旋转");
        updateButtons();
        if (auto) runRound();
    }

    async function undo() {
        if (busy) return;
        if (proposals) { dropProposals("已取消本轮建议填充"); return; }
        var batch = history.pop();
        if (!batch) { setStatus("没有可后退的填充"); return; }
        busy = true; updateButtons();
        clearErrorMarks();
        for (var i = batch.length - 1; i >= 0; i--) {
            var b = batch[i], el = b.el;
            if (!document.contains(el)) continue;
            var now = readStatus(el);
            var plain = (now - b.before + 8) % 4, ctrl = (b.before - now + 8) % 4;
            var useCtrl = ctrl < plain, times = useCtrl ? ctrl : plain;
            for (var n = 0; n < times; n++) { fireClick(el, useCtrl); await sleep(25); }
        }
        // 撤销后，若没有更早的批次填充过同一格，则取消它的蓝色标记
        batch.forEach(function (b) {
            var earlier = history.some(function (g) {
                return g.some(function (e) { return e.el === b.el; });
            });
            if (!earlier) autoFilled.delete(b.el);
        });
        refreshFillMarks();
        busy = false;
        setStatus("已后退：撤销上一次填充（" + batch.length + " 格）");
        updateButtons();
    }

    function buildPanel() {
        panel = document.createElement("div");
        panel.id = "pl-helper";
        panel.innerHTML =
            '<div class="pl-title" id="pl-drag">🧩 规则推理助手</div>' +
            '<div class="pl-row"><label><input type="checkbox" id="pl-auto"> 自动推理（后台跑，出错即停）</label></div>' +
            '<div class="pl-row"><label><input type="checkbox" id="pl-fillshow" checked> 显示自动填充区域（蓝色常亮）</label></div>' +
            '<div class="pl-status" id="pl-status">勾选「自动推理」开始；橙色常亮 = 建议旋转，确认后才真正填充。</div>' +
            '<div class="pl-btns">' +
            '<button id="pl-main" disabled>重新推理</button>' +
            '<button id="pl-back" disabled>后退</button>' +
            "</div>" +
            '<div class="pl-hint">橙=待确认建议；蓝=扩展填充过（可开关）；红=推理出错涉及区域。' +
            "后退：取消建议 / 撤销上次填充；手动摆过的格子不会被改写。</div>";
        document.body.appendChild(panel);
        statusEl = panel.querySelector("#pl-status");
        mainBtn = panel.querySelector("#pl-main");
        backBtn = panel.querySelector("#pl-back");
        autoChk = panel.querySelector("#pl-auto");
        fillChk = panel.querySelector("#pl-fillshow");

        autoChk.addEventListener("change", function () {
            auto = autoChk.checked;
            if (auto) { runRound(); }
            else { dropProposals("自动推理已关闭"); }
        });
        fillChk.addEventListener("change", function () {
            fillShow = fillChk.checked;
            refreshFillMarks();
        });
        mainBtn.addEventListener("click", function () {
            if (proposals && proposals.length) applyProposals();
            else runRound();
        });
        backBtn.addEventListener("click", undo);

        // 简单拖动
        var drag = panel.querySelector("#pl-drag"), dragging = null;
        drag.addEventListener("mousedown", function (e) {
            var r = panel.getBoundingClientRect();
            dragging = { dx: e.clientX - r.x, dy: e.clientY - r.y };
            e.preventDefault();
        });
        document.addEventListener("mousemove", function (e) {
            if (!dragging) return;
            panel.style.left = (e.clientX - dragging.dx) + "px";
            panel.style.top = (e.clientY - dragging.dy) + "px";
        });
        document.addEventListener("mouseup", function () { dragging = null; });
    }

    function waitBoard() {
        var tries = 0;
        var timer = setInterval(function () {
            tries++;
            if (document.querySelector("#game .board-back > .cell")) {
                clearInterval(timer);
                if (mainBtn) { mainBtn.disabled = false; backBtn.disabled = false; }
                setStatus("棋盘就绪。勾选「自动推理」开始；橙色常亮 = 建议旋转（待确认），" +
                    "蓝色 = 扩展自动填充区域（可开关显示）。");
            } else if (tries > 40) {
                clearInterval(timer);
                setStatus("长时间未找到棋盘（页面结构变化或尚未开局）");
            }
        }, 500);
    }

    buildPanel();
    waitBoard();
})();
