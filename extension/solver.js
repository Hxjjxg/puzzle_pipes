"use strict";
/*
 * solver.js —— solver.py（纯规则推理 R1–R8，无搜索/无枚举/无回溯）的 JS 移植。
 * 与 python 版保持同一模型：
 *   poss["x,y"] = 该格还可能的形状集合（4-bit 管道掩码，1=右 2=上 4=左 8=下）
 *   edges["H,x,y"|"V,x,y"] = 1 需要连接 / -1 墙（缺省 0 未确定）
 * 推出矛盾时抛 Error（消息区分 成环/孤岛/无可能形状）。
 * 本文件不碰 DOM，可在页面与 node 里共用。
 */
var DIRS = ["R", "U", "L", "D"];
var BIT = { R: 1, U: 2, L: 4, D: 8 };
var DELTA = { R: [1, 0], U: [0, -1], L: [-1, 0], D: [0, 1] };
var OPP = { R: "L", L: "R", U: "D", D: "U" };
var DIR_CN = { R: "右", U: "上", L: "左", D: "下" };
var ARROW = { R: "→", U: "↑", L: "←", D: "↓" };

function rot4(m) { return ((m << 1) & 15) | (m >> 3); }

function orbitOf(m) {
    var s = new Set(), cur = m & 15, i;
    for (i = 0; i < 4; i++) { s.add(cur); cur = rot4(cur); }
    return s;
}

/* 盘面校验（游戏规则）：无悬空开口，且全部管道连成一个组 */
function boardCheck(w, h, maskAt) {
    var x, y, d, m, dx, dy, nx, ny, inside;
    for (y = 0; y < h; y++) for (x = 0; x < w; x++) {
        m = maskAt(x, y);
        for (d = 0; d < 4; d++) {
            if (m & BIT[DIRS[d]]) {
                dx = DELTA[DIRS[d]][0]; dy = DELTA[DIRS[d]][1];
                nx = x + dx; ny = y + dy;
                inside = nx >= 0 && nx < w && ny >= 0 && ny < h;
                if (!inside || !(maskAt(nx, ny) & BIT[OPP[DIRS[d]]]))
                    return { ok: false, msg: "格(" + (x + 1) + "," + (y + 1) + ") " + DIR_CN[DIRS[d]] + "开口悬空" };
            }
        }
    }
    var seen = new Set(["0,0"]), stack = [[0, 0]];
    while (stack.length) {
        var p = stack.pop(); x = p[0]; y = p[1];
        m = maskAt(x, y);
        for (d = 0; d < 4; d++) {
            if (m & BIT[DIRS[d]]) {
                nx = x + DELTA[DIRS[d]][0]; ny = y + DELTA[DIRS[d]][1];
                if (nx >= 0 && nx < w && ny >= 0 && ny < h && !seen.has(nx + "," + ny)) {
                    seen.add(nx + "," + ny); stack.push([nx, ny]);
                }
            }
        }
    }
    if (seen.size !== w * h)
        return { ok: false, msg: "只连通 " + seen.size + "/" + (w * h) + " 格" };
    return { ok: true, msg: "无悬空开口且全部连通" };
}

var PipesSolver = function (w, h, task) {
    this.w = w; this.h = h; this.task = task;          // task[y][x] = 题面掩码
    this.poss = new Map();
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++)
        this.poss.set(x + "," + y, orbitOf(task[y][x]));
    this.edges = new Map();                            // 键 -> 1 / -1
    this.touched = new Set();                          // 本轮推理涉及过的格子 "x,y"
};

PipesSolver.prototype.touch = function (x, y) {
    this.touched.add(x + "," + y);
};

PipesSolver.prototype.ekey = function (x, y, d) {
    if (d === "R") return "H," + x + "," + y;
    if (d === "L") return "H," + (x - 1) + "," + y;
    if (d === "U") return "V," + x + "," + (y - 1);
    return "V," + x + "," + y;
};
PipesSolver.prototype.hasEdge = function (x, y, d) {
    var nx = x + DELTA[d][0], ny = y + DELTA[d][1];
    return nx >= 0 && nx < this.w && ny >= 0 && ny < this.h;
};
PipesSolver.prototype.edgeState = function (x, y, d) {
    if (!this.hasEdge(x, y, d)) return -1;             // 棋盘外一律是墙
    var v = this.edges.get(this.ekey(x, y, d));
    return v === undefined ? 0 : v;
};
PipesSolver.prototype.setEdge = function (x, y, d, state) {
    this.touch(x, y);
    this.touch(x + DELTA[d][0], y + DELTA[d][1]);
    var k = this.ekey(x, y, d), old = this.edges.get(k);
    if (old !== undefined && old !== state)
        throw new Error("连接冲突: 格(" + (x + 1) + "," + (y + 1) + ")的" + DIR_CN[d] +
            "方向这条边既被要求连接又被要求是墙（检查手工摆放）");
    this.edges.set(k, state);
};
/* 人工假设：把某格的可能性钉死为当前盘面显示的形状 */
PipesSolver.prototype.assume = function (x, y, mask) {
    this.poss.set(x + "," + y, new Set([mask]));
    this.touch(x, y);
};
PipesSolver.prototype.maskAt = function (x, y) {
    var s = this.poss.get(x + "," + y);
    if (!s || s.size !== 1) return undefined;
    for (var v of s) return v;
};

/* R1 边界排除：朝棋盘外的开口不可能（外圈的 T 型、直线型由此直接确定） */
PipesSolver.prototype.stepBorder = function () {
    for (var y = 0; y < this.h; y++) for (var x = 0; x < this.w; x++) {
        var walls = DIRS.filter(function (d) { return !this.hasEdge(x, y, d); }, this);
        if (!walls.length) continue;
        var s = this.poss.get(x + "," + y), self = this;
        var nw = new Set();
        s.forEach(function (m) {
            var bad = walls.some(function (d) { return m & BIT[d]; });
            if (!bad) nw.add(m);
        });
        if (nw.size === s.size) continue;
        if (!nw.size) throw new Error("格(" + (x + 1) + "," + (y + 1) + ") 无可能形状");
        this.poss.set(x + "," + y, nw);
        this.touch(x, y);
    }
};

/* R2 确定格子推边：开口 -> 需要连接，非开口 -> 墙 */
PipesSolver.prototype.stepR2 = function () {
    for (var [key, s] of this.poss) {
        if (s.size !== 1) continue;
        var x = +key.split(",")[0], y = +key.split(",")[1];
        var states = DIRS.map(function (d) { return this.edgeState(x, y, d); }, this);
        if (states.indexOf(0) < 0) continue;           // 四个方向的边都已定
        var m, it = s.values(); m = it.next().value;
        var self = this;
        DIRS.forEach(function (d) {
            if (m & BIT[d]) {
                if (!self.hasEdge(x, y, d))
                    throw new Error("格(" + (x + 1) + "," + (y + 1) + ") 开口朝棋盘外");
                self.setEdge(x, y, d, 1);
            } else if (self.hasEdge(x, y, d)) {
                self.setEdge(x, y, d, -1);
            }
        });
        return true;
    }
    return false;
};

/* R3 边推格子：边上的连接要求排除不可能形状 */
PipesSolver.prototype.stepR3 = function () {
    for (var [key, s] of this.poss) {
        if (s.size === 1) continue;
        var x = +key.split(",")[0], y = +key.split(",")[1], self = this;
        for (var di = 0; di < 4; di++) {
            var d = DIRS[di], st = this.edgeState(x, y, d);
            if (st === 0) continue;
            var want = st === 1, nw = new Set();
            s.forEach(function (m) { if ((!!(m & BIT[d])) === want) nw.add(m); });
            if (nw.size === s.size) continue;
            if (!nw.size) throw new Error("格(" + (x + 1) + "," + (y + 1) + ") 无可能形状");
            this.poss.set(key, nw);
            this.touch(x, y);
            return true;
        }
    }
    return false;
};

/* R4 一致推边：剩余所有形状都（不）朝某方向开口 -> 该边定为（墙）需要连接 */
PipesSolver.prototype.stepR4 = function () {
    for (var [key, s] of this.poss) {
        if (s.size === 1) continue;
        var x = +key.split(",")[0], y = +key.split(",")[1];
        for (var di = 0; di < 4; di++) {
            var d = DIRS[di];
            if (this.edgeState(x, y, d) !== 0) continue;
            var nOpen = 0;
            s.forEach(function (m) { if (m & BIT[d]) nOpen++; });
            if (nOpen !== s.size && nOpen !== 0) continue;
            this.setEdge(x, y, d, nOpen === s.size ? 1 : -1);
            return true;
        }
    }
    return false;
};

PipesSolver.prototype._cellsOf = function (key) {
    var p = key.split(","), o = p[0], x = +p[1], y = +p[2];
    if (o === "H") return [[x, y], [x + 1, y]];
    return [[x, y], [x, y + 1]];
};
PipesSolver.prototype._setEdgeKey = function (key, state) {
    var p = key.split(",");
    this.setEdge(+p[1], +p[2], p[0] === "H" ? "R" : "D", state);
};

/* 一轮全局推理（生成树性质）：R5/R6 查矛盾，R7/R8 推新边。应用了新边返回 true */
PipesSolver.prototype.stepGlobal = function () {
    var w = this.w, h = this.h, x, y, self = this;
    // R5: 确定连接边建并查集，必须构成森林；统计每块的大小与内部确定边数
    var root = new Map(), size = new Map(), ecount = new Map();
    for (y = 0; y < h; y++) for (x = 0; x < w; x++) {
        root.set(x + "," + y, x + "," + y);
        size.set(x + "," + y, 1);
        ecount.set(x + "," + y, 0);
    }
    function find(a) {
        while (root.get(a) !== a) { root.set(a, root.get(root.get(a))); a = root.get(a); }
        return a;
    }
    var keys = [];
    this.edges.forEach(function (v, k) { if (v === 1) keys.push(k); });
    for (var i = 0; i < keys.length; i++) {
        var ab = this._cellsOf(keys[i]), a = ab[0], b = ab[1];
        var ka = a[0] + "," + a[1], kb = b[0] + "," + b[1];
        var ra = find(ka), rb = find(kb);
        if (ra === rb) {
            this.touch(a[0], a[1]);
            this.touch(b[0], b[1]);
            throw new Error("成环: 格(" + (a[0] + 1) + "," + (a[1] + 1) + ")与格(" +
                (b[0] + 1) + "," + (b[1] + 1) + ")之间的确定连接围成闭环");
        }
        if (size.get(ra) < size.get(rb)) { var t = ra; ra = rb; rb = t; }
        root.set(rb, ra);
        size.set(ra, size.get(ra) + size.get(rb));
        ecount.set(ra, ecount.get(ra) + ecount.get(rb) + 1);
    }
    var k = 0;
    root.forEach(function (v, c) { if (find(c) === c) k++; });

    // R6: 把"未确定∪需要连接"的边洪泛，不连通说明必然出现孤岛
    var seen = new Set(), comps = [];
    for (y = 0; y < h; y++) for (x = 0; x < w; x++) {
        if (seen.has(x + "," + y)) continue;
        var comp = [x + "," + y], stack = [[x, y]];
        seen.add(x + "," + y);
        while (stack.length) {
            var p = stack.pop(), cx = p[0], cy = p[1];
            for (var di = 0; di < 4; di++) {
                var d = DIRS[di];
                if (self.hasEdge(cx, cy, d) && self.edgeState(cx, cy, d) !== -1) {
                    var nx = cx + DELTA[d][0], ny = cy + DELTA[d][1], nk = nx + "," + ny;
                    if (!seen.has(nk)) { seen.add(nk); comp.push(nk); stack.push([nx, ny]); }
                }
            }
        }
        comps.push(comp);
    }
    if (comps.length > 1) {
        comps.sort(function (a, b) { return a.length - b.length; });
        var small = comps[0], pp = small[0].split(",");
        var self2 = this;
        small.forEach(function (kk) {
            var q = kk.split(",");
            self2.touch(+q[0], +q[1]);
        });
        throw new Error("孤岛: " + small.length + "格区域（如(" + (+pp[0] + 1) + "," + (+pp[1] + 1) +
            ")）与其余" + (w * h - small.length) + "格被墙隔死");
    }

    // 未确定边分类：跨块（出口）/ 块内（注意：未确定边不在 edges 里，要按结构枚举）
    var cross = [], esc = new Map(), internal = new Map();
    var all = [];
    for (y = 0; y < h; y++) for (x = 0; x < w - 1; x++) all.push("H," + x + "," + y);
    for (y = 0; y < h - 1; y++) for (x = 0; x < w; x++) all.push("V," + x + "," + y);
    for (i = 0; i < all.length; i++) {
        var key = all[i];
        if ((this.edges.get(key) || 0) !== 0) continue;
        var ab2 = this._cellsOf(key), a2 = ab2[0], b2 = ab2[1];
        var ra2 = find(a2[0] + "," + a2[1]), rb2 = find(b2[0] + "," + b2[1]);
        if (ra2 === rb2) {
            if (!internal.has(ra2)) internal.set(ra2, []);
            internal.get(ra2).push(key);
        } else {
            cross.push(key);
            esc.set(ra2, (esc.get(ra2) || 0) + 1);
            esc.set(rb2, (esc.get(rb2) || 0) + 1);
        }
    }

    // R7: 某连通块只剩一个出口 -> 该边必连
    var r7root = null;
    esc.forEach(function (n, r) { if (n === 1 && !r7root) r7root = r; });
    if (r7root !== null) {
        for (i = 0; i < cross.length; i++) {
            var ab3 = this._cellsOf(cross[i]);
            if (find(ab3[0][0] + "," + ab3[0][1]) === r7root ||
                find(ab3[1][0] + "," + ab3[1][1]) === r7root) {
                this._setEdgeKey(cross[i], 1);
                return true;
            }
        }
    }

    // R8a: 跨块预算 —— 树需要恰 k-1 条跨块边；恰好只剩这么多条时全部必连
    var need = k - 1;
    if (cross.length < need)
        throw new Error("孤岛: " + k + "个连通块需要" + need + "条跨块连接，但只剩" + cross.length + "条通路");
    if (need > 0 && cross.length === need) {
        this._setEdgeKey(cross[0], 1);
        return true;
    }

    // R8b: 块内容量 —— 内部确定边已满 c-1 条（已是树），剩余内部未知边全是墙
    var r8root = null, r8keys = null;
    internal.forEach(function (ks, r) {
        if (ecount.get(r) === size.get(r) - 1 && ks.length && !r8root) { r8root = r; r8keys = ks; }
    });
    if (r8root !== null) {
        this._setEdgeKey(r8keys[0], -1);
        return true;
    }
    return false;
};

PipesSolver.prototype.propagate = function () {
    while (true) {
        if (this.stepR2() || this.stepR3() || this.stepR4()) continue;
        if (this.stepGlobal()) continue;
        break;
    }
};

PipesSolver.prototype.run = function () {
    this.stepBorder();
    this.propagate();
};

PipesSolver.prototype.isSolved = function () {
    var ok = true;
    this.poss.forEach(function (s) { if (s.size !== 1) ok = false; });
    return ok;
};
PipesSolver.prototype.determinedCount = function () {
    var n = 0;
    this.poss.forEach(function (s) { if (s.size === 1) n++; });
    return n;
};

/* 每格最小旋转次数（与官方校验串一致：直线型周期为 2） */
PipesSolver.prototype.rotations = function () {
    var out = [];
    for (var y = 0; y < this.h; y++) for (var x = 0; x < this.w; x++) {
        var target = this.maskAt(x, y), cur = this.task[y][x], kk = 0;
        for (var i = 0; i < 4; i++) {
            if (cur === target) { kk = i; break; }
            cur = rot4(cur);
        }
        out.push(kk);
    }
    return out;
};

if (typeof module !== "undefined" && module.exports)
    module.exports = { PipesSolver: PipesSolver, rot4: rot4, orbitOf: orbitOf, boardCheck: boardCheck,
                       DIRS: DIRS, BIT: BIT, DELTA: DELTA, OPP: OPP };
