"use strict";
/*
 * solver.js —— solver.py 的 JS 移植（规则推理 R1–R9 + 可选 DFS/回溯搜索）。
 * 与 python 版保持同一模型：
 *   poss["x,y"] = 该格还可能的形状集合（4-bit 管道掩码，1=右 2=上 4=左 8=下）
 *   edges["H,x,y"|"V,x,y"] = 1 需要连接 / -1 墙（缺省 0 未确定）
 * 推出矛盾时抛 Error（消息区分 成环/孤岛/无可能形状）。
 *
 * wrap（环形穿墙）模式：wrap=true 时棋盘左右/上下相接成环面（torus），
 * 没有"棋盘外"，所有格子恒有四个方向；边键与两端坐标一律取模。
 * 此时 R1 不再产生任何推理，开局规则传播一步都推不动，需要 search() 枚举。
 * 另有 wrap 专属 R9：某行/列的整圈边只剩一条未定而其余全连接时，该边必是墙。
 *
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

/* 盘面校验（游戏规则）：无悬空开口，且全部管道连成一个组。
   wrap=true 时上下/左右相接，邻居与连通洪泛都按环面取模。 */
function boardCheck(w, h, maskAt, wrap) {
    var x, y, d, m, nx, ny, inside;
    function neigh(x, y, d) {
        var nx = x + DELTA[d][0], ny = y + DELTA[d][1];
        if (wrap) return [(nx % w + w) % w, (ny % h + h) % h];
        return [nx, ny];
    }
    for (y = 0; y < h; y++) for (x = 0; x < w; x++) {
        m = maskAt(x, y);
        for (d = 0; d < 4; d++) {
            if (m & BIT[DIRS[d]]) {
                var nb = neigh(x, y, DIRS[d]);
                nx = nb[0]; ny = nb[1];
                inside = wrap || (nx >= 0 && nx < w && ny >= 0 && ny < h);
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
                var nb2 = neigh(x, y, DIRS[d]);
                nx = nb2[0]; ny = nb2[1];
                if ((wrap || (nx >= 0 && nx < w && ny >= 0 && ny < h)) && !seen.has(nx + "," + ny)) {
                    seen.add(nx + "," + ny); stack.push([nx, ny]);
                }
            }
        }
    }
    if (seen.size !== w * h)
        return { ok: false, msg: "只连通 " + seen.size + "/" + (w * h) + " 格" };
    return { ok: true, msg: "无悬空开口且全部连通" };
}

var PipesSolver = function (w, h, task, wrap) {
    this.w = w; this.h = h; this.task = task;          // task[y][x] = 题面掩码
    this.wrap = !!wrap;
    this.poss = new Map();
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++)
        this.poss.set(x + "," + y, orbitOf(task[y][x]));
    this.edges = new Map();                            // 键 -> 1 / -1
    this.touched = new Set();                          // 本轮推理涉及过的格子 "x,y"
    this.searchStats = null;
};

function mod(a, n) { return ((a % n) + n) % n; }

PipesSolver.prototype.touch = function (x, y) {
    if (this.wrap) { x = mod(x, this.w); y = mod(y, this.h); }
    this.touched.add(x + "," + y);
};

PipesSolver.prototype.ekey = function (x, y, d) {
    if (d === "R") return "H," + mod(x, this.w) + "," + y;
    if (d === "L") return "H," + mod(x - 1, this.w) + "," + y;
    if (d === "U") return "V," + x + "," + mod(y - 1, this.h);
    return "V," + x + "," + mod(y, this.h);
};
PipesSolver.prototype.hasEdge = function (x, y, d) {
    if (this.wrap) return true;
    var nx = x + DELTA[d][0], ny = y + DELTA[d][1];
    return nx >= 0 && nx < this.w && ny >= 0 && ny < this.h;
};
/* 朝 d 方向的相邻格；wrap 取模，非 wrap 越界返回 null */
PipesSolver.prototype.neighbor = function (x, y, d) {
    var nx = x + DELTA[d][0], ny = y + DELTA[d][1];
    if (this.wrap) return [mod(nx, this.w), mod(ny, this.h)];
    if (nx >= 0 && nx < this.w && ny >= 0 && ny < this.h) return [nx, ny];
    return null;
};
/* 盘面上全部相邻格的边键（wrap 时含首尾相接的边） */
PipesSolver.prototype.allEdges = function () {
    var out = [], x, y;
    for (y = 0; y < this.h; y++)
        for (x = 0; x < (this.wrap ? this.w : this.w - 1); x++)
            out.push("H," + x + "," + y);
    for (y = 0; y < (this.wrap ? this.h : this.h - 1); y++)
        for (x = 0; x < this.w; x++)
            out.push("V," + x + "," + y);
    return out;
};
PipesSolver.prototype.edgeState = function (x, y, d) {
    if (!this.hasEdge(x, y, d)) return -1;             // 棋盘外一律是墙
    var v = this.edges.get(this.ekey(x, y, d));
    return v === undefined ? 0 : v;
};
PipesSolver.prototype.setEdge = function (x, y, d, state) {
    this.touch(x, y);
    var nb = this.neighbor(x, y, d);
    if (nb) this.touch(nb[0], nb[1]);
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

/* R1 边界排除：朝棋盘外的开口不可能（外圈的 T 型、直线型由此直接确定）。
   wrap 时没有棋盘外，此规则自然空转。 */
PipesSolver.prototype.stepBorder = function () {
    for (var y = 0; y < this.h; y++) for (var x = 0; x < this.w; x++) {
        var walls = DIRS.filter(function (d) { return !this.hasEdge(x, y, d); }, this);
        if (!walls.length) continue;
        var s = this.poss.get(x + "," + y);
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
        var x = +key.split(",")[0], y = +key.split(",")[1];
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
    if (o === "H") return [[x, y], [mod(x + 1, this.w), y]];
    return [[x, y], [x, mod(y + 1, this.h)]];
};
PipesSolver.prototype._setEdgeKey = function (key, state) {
    var p = key.split(",");
    this.setEdge(+p[1], +p[2], p[0] === "H" ? "R" : "D", state);
};

/* 一轮全局推理（生成树性质）：R5/R6 查矛盾，R7/R8/R9 推新边。应用了新边返回 true */
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
                if (self.edgeState(cx, cy, d) === -1) continue;
                var nb = self.neighbor(cx, cy, d);
                if (!nb) continue;
                var nk = nb[0] + "," + nb[1];
                if (!seen.has(nk)) { seen.add(nk); comp.push(nk); stack.push(nb); }
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

    // 未确定边分类：跨块（出口）/ 块内（未确定边不在 edges 里，要按结构枚举）
    var cross = [], esc = new Map(), internal = new Map();
    var all = this.allEdges();
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
    esc.forEach(function (n, r) { if (n === 1 && r7root === null) r7root = r; });
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
        if (ecount.get(r) === size.get(r) - 1 && ks.length && r8root === null) { r8root = r; r8keys = ks; }
    });
    if (r8root !== null) {
        this._setEdgeKey(r8keys[0], -1);
        return true;
    }

    // R9（仅 wrap）：环面上每行 w 条横边、每列 h 条竖边各自成环，
    // 生成树不能整圈取连接 -> 某行/列只剩一条未定且其余全连接时，该边必是墙。
    if (this.wrap) {
        for (y = 0; y < h; y++) {
            var unkH = [], allConH = true;
            for (x = 0; x < w; x++) {
                var rhk = "H," + x + "," + y, rhv = this.edges.get(rhk);
                if (rhv === undefined) unkH.push(rhk);
                else if (rhv !== 1) { allConH = false; break; }
            }
            if (allConH && unkH.length === 1) { this._setEdgeKey(unkH[0], -1); return true; }
        }
        for (x = 0; x < w; x++) {
            var unkV = [], allConV = true;
            for (y = 0; y < h; y++) {
                var rvk = "V," + x + "," + y, rvv = this.edges.get(rvk);
                if (rvv === undefined) unkV.push(rvk);
                else if (rvv !== 1) { allConV = false; break; }
            }
            if (allConV && unkV.length === 1) { this._setEdgeKey(unkV[0], -1); return true; }
        }
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

/* ---------- DFS / 回溯搜索（对应 solver.py 的 _dfs/search） ---------- */

PipesSolver.prototype._stateCopy = function () {
    var poss = new Map(), edges = new Map(this.edges);
    this.poss.forEach(function (v, k) { poss.set(k, new Set(v)); });
    return { poss: poss, edges: edges };
};
PipesSolver.prototype._restoreState = function (st) {
    this.poss = st.poss; this.edges = st.edges;
};
PipesSolver.prototype._unknownDegree = function (x, y) {
    var n = 0, i;
    for (i = 0; i < 4; i++) if (this.edgeState(x, y, DIRS[i]) === 0) n++;
    return n;
};
/* 未知边取 1/墙时，两端候选形状的支持数乘积，用于 edge 策略 */
PipesSolver.prototype._edgeSupport = function (key) {
    var ab = this._cellsOf(key), a = ab[0], b = ab[1];
    var dA = key.charAt(0) === "H" ? "R" : "D", dB = OPP[dA];
    var sa = this.poss.get(a[0] + "," + a[1]), sb = this.poss.get(b[0] + "," + b[1]);
    var openA = 0, openB = 0;
    sa.forEach(function (m) { if (m & BIT[dA]) openA++; });
    sb.forEach(function (m) { if (m & BIT[dB]) openB++; });
    return [openA * openB, (sa.size - openA) * (sb.size - openB)];
};
/* 选择分支变量：返回 {kind:"cell"|"edge", target, values} */
PipesSolver.prototype.selectBranch = function (strategy) {
    var self = this;
    if (strategy === "first") {
        for (var [key, s] of this.poss)
            if (s.size > 1) return { kind: "cell", target: key, values: Array.from(s).sort(function (a, b) { return a - b; }) };
    }
    if (strategy === "edge") {
        var best = null;
        this.allEdges().forEach(function (key) {
            if ((self.edges.get(key) || 0) !== 0) return;
            var sup = self._edgeSupport(key);
            var score = Math.min(sup[0], sup[1]) * 1e6 + (sup[0] + sup[1]);
            if (best === null || score < best.score) best = { score: score, key: key, sup: sup };
        });
        var vals = best.sup[0] <= best.sup[1] ? [1, -1] : [-1, 1];
        return { kind: "edge", target: best.key, values: vals };
    }
    // 默认 mrv：候选最少的格子，平手取未知邻边更多的
    var bestCell = null, bestSize = Infinity, bestDeg = -1;
    this.poss.forEach(function (s, key) {
        if (s.size <= 1) return;
        var p = key.split(","), x = +p[0], y = +p[1];
        var deg = self._unknownDegree(x, y);
        if (s.size < bestSize || (s.size === bestSize && deg > bestDeg)) {
            bestSize = s.size; bestDeg = deg;
            bestCell = { key: key, vals: Array.from(s).sort(function (a, b) { return a - b; }) };
        }
    });
    return { kind: "cell", target: bestCell.key, values: bestCell.vals };
};

/* 在规则传播不动点之后做 DFS + 回溯；成功时把解留在当前状态里。
   opts: { strategy:"mrv"|"first"|"edge", maxNodes, timeoutMs }
   返回 { solved, nodes, decisions, contradictions, depth, limited, timeout } */
PipesSolver.prototype.search = function (opts) {
    opts = opts || {};
    var strategy = opts.strategy || "mrv";
    var maxNodes = opts.maxNodes || 500000;
    var deadline = opts.timeoutMs ? Date.now() + opts.timeoutMs : 0;
    var self = this;
    var stats = { strategy: strategy, solved: false, nodes: 0, decisions: 0,
                  contradictions: 0, depth: 0, limited: false, timeout: false };
    var LIMIT = { __limit: true };

    function dfs(depth) {
        stats.nodes++;
        if (stats.nodes > maxNodes) { stats.limited = true; throw LIMIT; }
        if (deadline && (stats.nodes & 63) === 0 && Date.now() > deadline) {
            stats.timeout = true; throw LIMIT;
        }
        if (depth > stats.depth) stats.depth = depth;

        if (self.isSolved()) {
            var chk = boardCheck(self.w, self.h, function (x, y) { return self.maskAt(x, y); }, self.wrap);
            if (chk.ok) return true;
            stats.contradictions++;
            return false;
        }
        var br = self.selectBranch(strategy);
        stats.decisions++;
        for (var i = 0; i < br.values.length; i++) {
            var snap = self._stateCopy();
            try {
                if (br.kind === "cell") self.poss.set(br.target, new Set([br.values[i]]));
                else self._setEdgeKey(br.target, br.values[i]);
                self.propagate();
                if (dfs(depth + 1)) return true;
            } catch (e) {
                if (e === LIMIT) { self._restoreState(snap); throw e; }
                stats.contradictions++;
            }
            self._restoreState(snap);
        }
        return false;
    }

    this.run();
    try { stats.solved = dfs(0); }
    catch (e) { if (e !== LIMIT) throw e; }
    this.searchStats = stats;
    return stats;
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
