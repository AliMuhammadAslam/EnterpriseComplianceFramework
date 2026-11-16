// Compliance dashboard: charts drawn as SVG from /dashboard/data.
// Report text is written by the model, so every string from the data is set
// with textContent, never as HTML.
(function () {
    "use strict";

    const SVG_NS = "http://www.w3.org/2000/svg";
    const BAND_VAR = { "Immediate": "--dv-critical", "Medium-term": "--dv-serious", "Long-term": "--dv-warning" };
    const STATUS_VAR = { "Findings": "--dv-cov-1", "Documentation gap": "--dv-cov-2", "Not applicable": "--dv-cov-3" };
    const RAMP = ["--dv-ramp-1", "--dv-ramp-2", "--dv-ramp-3", "--dv-ramp-4", "--dv-ramp-5"];

    const state = { data: null, selectedId: null, trendMetric: "gaps", tables: {}, loading: false };
    let root = null;
    let tooltip = null;
    let resizeTimer = null;

    // ---------------------------------------------------------------- helpers
    function el(tag, attrs, children) {
        const node = document.createElement(tag);
        for (const [k, v] of Object.entries(attrs || {})) {
            if (k === "text") node.textContent = v;
            else if (k === "class") node.className = v;
            else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
            else node.setAttribute(k, v);
        }
        for (const c of [].concat(children || [])) if (c) node.appendChild(c);
        return node;
    }
    function svg(tag, attrs, children) {
        const node = document.createElementNS(SVG_NS, tag);
        for (const [k, v] of Object.entries(attrs || {})) {
            if (k === "text") node.textContent = v;
            else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
            else node.setAttribute(k, v);
        }
        for (const c of [].concat(children || [])) if (c) node.appendChild(c);
        return node;
    }
    const cssVar = (name) => getComputedStyle(root).getPropertyValue(name).trim();
    const sum = (xs) => xs.reduce((a, b) => a + b, 0);

    // Text colour for a label on a filled mark: whichever of near-black or
    // white has the higher WCAG contrast against the fill.
    function luminance(hex) {
        const c = hex.replace("#", "");
        const ch = [0, 2, 4].map(i => parseInt(c.substr(i, 2), 16) / 255)
            .map(v => v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4));
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
    }
    function inkOn(hex) {
        const L = luminance(hex);
        const vsWhite = 1.05 / (L + 0.05), vsDark = (L + 0.05) / (luminance("#0f172a") + 0.05);
        return vsWhite >= vsDark ? "#ffffff" : "#0f172a";
    }

    function fmtDate(ts, withTime) {
        if (!ts) return "Unknown date";
        const d = new Date(ts);
        if (isNaN(d)) return String(ts);
        const opts = { day: "numeric", month: "short", year: "numeric" };
        if (withTime) Object.assign(opts, { hour: "2-digit", minute: "2-digit" });
        return d.toLocaleString(undefined, opts);
    }
    function shortDate(ts) {
        const d = new Date(ts);
        return isNaN(d) ? "?" : d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
    }
    function truncate(text, max) {
        return text.length > max ? text.slice(0, max - 1) + "…" : text;
    }
    // Whole-number axis step (1, 2, 5, 10, 20, 50...) giving at most about six
    // gridlines; every gridline sits exactly at the value it is labelled with.
    function axisStep(v) {
        const raw = Math.max(1, v) / 5;
        const pow = Math.pow(10, Math.floor(Math.log10(raw)));
        const n = raw / pow;
        return Math.max(1, Math.round((n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * pow));
    }
    function niceMax(v) {
        const step = axisStep(v);
        return Math.max(step, Math.ceil(Math.max(1, v) / step) * step);
    }
    function ticks(max) {
        const step = axisStep(max);
        const out = [];
        for (let t = 0; t <= max; t += step) out.push(t);
        return out;
    }

    const ICONS = {
        alert: '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
        flag: '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/>',
        target: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
        file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="9" y1="15" x2="15" y2="15"/>',
        refresh: '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
    };
    function icon(name) {
        const s = document.createElementNS(SVG_NS, "svg");
        s.setAttribute("viewBox", "0 0 24 24");
        s.setAttribute("aria-hidden", "true");
        s.innerHTML = ICONS[name];  // fixed markup above, no data
        return s;
    }

    // ---------------------------------------------------------------- tooltip
    function showTip(evt, lines) {
        tooltip.replaceChildren();
        lines.forEach((line, i) => {
            if (Array.isArray(line)) {
                tooltip.appendChild(el("div", { class: "dv-tt-row" }, [el("span", { text: line[0] }), el("b", { text: String(line[1]) })]));
            } else {
                tooltip.appendChild(i === 0 ? el("b", { text: line }) : el("div", { text: line }));
            }
        });
        let x, y;
        if (evt && evt.clientX !== undefined && evt.type !== "focus") {
            x = evt.clientX; y = evt.clientY;
        } else {
            const r = evt.target.getBoundingClientRect();
            x = r.left + r.width / 2; y = r.top;
        }
        tooltip.classList.add("show");
        const tw = tooltip.offsetWidth, th = tooltip.offsetHeight;
        let left = x + 14, top = y - th - 10;
        if (left + tw > window.innerWidth - 8) left = x - tw - 14;
        if (top < 8) top = y + 16;
        tooltip.style.left = `${Math.max(8, left)}px`;
        tooltip.style.top = `${top}px`;
    }
    function hideTip() { if (tooltip) tooltip.classList.remove("show"); }
    function bindTip(node, lines, label) {
        node.setAttribute("tabindex", "0");
        node.setAttribute("role", "img");
        node.setAttribute("aria-label", label || lines.map(l => Array.isArray(l) ? `${l[0]} ${l[1]}` : l).join(", "));
        node.classList.add("dv-mark");
        node.addEventListener("pointerenter", e => showTip(e, lines));
        node.addEventListener("pointermove", e => showTip(e, lines));
        node.addEventListener("pointerleave", hideTip);
        node.addEventListener("focus", e => showTip(e, lines));
        node.addEventListener("blur", hideTip);
    }

    // ---------------------------------------------------------------- data
    function reports() { return (state.data && state.data.reports) || []; }
    function selected() {
        const list = reports();
        return list.find(r => r.report_id === state.selectedId) || list[list.length - 1] || null;
    }
    function previousOf(report) {
        const list = reports();
        const i = list.indexOf(report);
        return i > 0 ? list[i - 1] : null;
    }
    // A figure whose table could not be read is null, shown as "not available",
    // never as zero: "unreadable" is not the same as "no gaps".
    function metrics(r) {
        const gaps = r.gaps;
        const risk = r.risk_table_found, cov = r.coverage_found;
        const top = gaps.reduce((best, g) => (!best || g.score > best.score ? g : best), null);
        return {
            gaps: risk ? gaps.length : null,
            immediate: risk ? gaps.filter(g => g.band === "Immediate").length : null,
            topScore: risk ? (top ? top.score : 0) : null,
            topGap: risk ? top : null,
            totalScore: risk ? sum(gaps.map(g => g.score)) : null,
            docGaps: cov ? r.coverage.filter(c => c.status === "Documentation gap").length : null,
            assessed: cov ? r.coverage.length : null,
        };
    }
    const shown = (v) => (v === null || v === undefined ? "\u2014" : String(v));
    const riskReadable = () => reports().filter(x => x.risk_table_found);
    const coverageReadable = () => reports().filter(x => x.coverage_found);

    // ---------------------------------------------------------------- layout
    function card(title, sub, key, body, tableBuilder, extraTools) {
        const tools = el("div", { class: "dv-card-tools" }, extraTools || []);
        if (tableBuilder) {
            const showing = !!state.tables[key];
            tools.appendChild(el("button", {
                class: "dv-link", type: "button", "aria-pressed": String(showing),
                text: showing ? "Show chart" : "Show table",
                onclick: () => { state.tables[key] = !showing; render(); },
            }));
        }
        const content = state.tables[key] && tableBuilder ? tableBuilder() : body;
        return el("section", { class: "dv-card", "aria-label": title }, [
            el("div", { class: "dv-card-head" }, [el("h3", { class: "dv-card-title", text: title }), tools]),
            sub ? el("p", { class: "dv-card-sub", text: sub }) : null,
            content,
        ]);
    }
    function table(headers, rows, numericCols) {
        const nums = new Set(numericCols || []);
        return el("table", { class: "dv-table" }, [
            el("thead", {}, [el("tr", {}, headers.map((h, i) => el("th", { class: nums.has(i) ? "num" : "", text: h })))]),
            el("tbody", {}, rows.map(r => el("tr", {}, r.map((c, i) => el("td", { class: nums.has(i) ? "num" : "", text: String(c) }))))),
        ]);
    }
    function emptyNote(text) {
        return el("p", { class: "dv-card-sub", text, style: "margin:0.75rem 0 0.25rem" });
    }
    function widthOf(container, fallback) {
        return Math.max(240, Math.floor((container && container.clientWidth) || fallback));
    }

    // ---------------------------------------------------------------- KPI cards
    function sparkline(values) {
        const w = 92, h = 28, pad = 3;
        const s = svg("svg", { class: "dv-spark", viewBox: `0 0 ${w} ${h}`, "aria-hidden": "true" });
        if (values.length < 2) return s;
        const max = Math.max(...values, 1), min = Math.min(...values, 0);
        const span = max - min || 1;
        const pts = values.map((v, i) => [pad + i * (w - 2 * pad) / (values.length - 1), h - pad - (v - min) / span * (h - 2 * pad)]);
        const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
        s.appendChild(svg("path", { class: "area", d: `${line} L${pts[pts.length - 1][0]},${h} L${pts[0][0]},${h} Z` }));
        s.appendChild(svg("path", { class: "line", d: line }));
        const last = pts[pts.length - 1];
        s.appendChild(svg("circle", { cx: last[0], cy: last[1], r: 2.5 }));
        return s;
    }
    function kpi(iconName, value, label, accentVar, delta, note, series) {
        const node = el("div", { class: "dv-kpi", role: "group", "aria-label": `${label}: ${value === null ? "not available" : value}` }, [
            el("div", { class: "dv-kpi-top" }, [
                el("div", { class: "dv-kpi-icon" }, [icon(iconName)]),
                el("div", {}, [el("div", { class: "dv-kpi-value", text: shown(value) }), el("div", { class: "dv-kpi-label", text: label })]),
            ]),
            el("div", { class: "dv-kpi-foot" }, [delta || note || el("span"), sparkline(series)]),
        ]);
        node.style.setProperty("--kpi-accent", cssVar(accentVar));
        return node;
    }
    function deltaBadge(now, before) {
        if (now === null) return el("span", { class: "dv-kpi-delta neutral", text: "Table not readable" });
        if (before === undefined) return el("span", { class: "dv-kpi-delta neutral", text: "First evaluation" });
        if (before === null) return el("span", { class: "dv-kpi-delta neutral", text: "Previous not readable" });
        const d = now - before;
        if (d === 0) return el("span", { class: "dv-kpi-delta neutral", text: "No change vs previous" });
        const cls = d > 0 ? "up-bad" : "down-good";
        return el("span", { class: `dv-kpi-delta ${cls}`, text: `${d > 0 ? "▲" : "▼"} ${Math.abs(d)} vs previous` });
    }
    function kpiRow(r) {
        const m = metrics(r), prev = previousOf(r), pm = prev ? metrics(prev) : null;
        const upTo = reports().slice(0, reports().indexOf(r) + 1).map(metrics);
        const series = (key) => upTo.map(x => x[key]).filter(v => v !== null);
        const before = (key) => (pm ? pm[key] : undefined);
        const topNote = m.topScore === null
            ? el("span", { class: "dv-kpi-note", text: "Risk table not readable" })
            : m.topGap ? el("span", { class: "dv-kpi-note", title: m.topGap.gap, text: m.topGap.gap })
            : el("span", { class: "dv-kpi-note", text: "No scored gaps" });
        const docLabel = m.assessed === null ? "Documentation gaps" : `Documentation gaps (of ${m.assessed} standards)`;
        return el("div", { class: "dv-kpis" }, [
            kpi("alert", m.gaps, "Gaps found", "--dv-bar", deltaBadge(m.gaps, before("gaps")), null, series("gaps")),
            kpi("flag", m.immediate, "Immediate priority", "--dv-critical", deltaBadge(m.immediate, before("immediate")), null, series("immediate")),
            kpi("target", m.topScore, "Highest risk score", "--dv-serious", null, topNote, series("topScore")),
            kpi("file", m.docGaps, docLabel, "--dv-cov-2", deltaBadge(m.docGaps, before("docGaps")), null, series("docGaps")),
        ]);
    }

    // ---------------------------------------------------------------- charts
    function priorityBars(r, container) {
        const bands = state.data.bands;
        const counts = bands.map(b => r.gaps.filter(g => g.band === b).length);
        const w = widthOf(container, 300), h = 190, left = 30, right = 10, top = 22, bottom = 34;
        const max = niceMax(Math.max(...counts, 1));
        const s = svg("svg", { class: "dv-chart", viewBox: `0 0 ${w} ${h}`, role: "group", "aria-label": "Gaps by priority band" });
        const plotH = h - top - bottom, plotW = w - left - right;
        ticks(max).forEach(t => {
            const y = top + plotH - t / max * plotH;
            s.appendChild(svg("line", { class: "dv-gridline", x1: left, x2: w - right, y1: y, y2: y }));
            s.appendChild(svg("text", { class: "dv-axis-text", x: left - 6, y: y + 4, "text-anchor": "end", text: String(t) }));
        });
        const slot = plotW / bands.length, bw = Math.min(46, slot * 0.55);
        bands.forEach((b, i) => {
            const x = left + slot * i + (slot - bw) / 2;
            const bh = counts[i] / max * plotH, y = top + plotH - bh;
            const g = svg("g");
            if (bh > 0) g.appendChild(svg("path", { d: roundTop(x, y, bw, bh, 4), fill: cssVar(BAND_VAR[b]) }));
            g.appendChild(svg("text", { class: "dv-value-text", x: x + bw / 2, y: y - 6, "text-anchor": "middle", text: String(counts[i]) }));
            g.appendChild(svg("text", { class: "dv-cat-text", x: x + bw / 2, y: h - bottom + 16, "text-anchor": "middle", text: b }));
            const hit = svg("rect", { class: "dv-hit", x: left + slot * i, y: top, width: slot, height: plotH + 20 });
            bindTip(hit, [b, ["Gaps", counts[i]]], `${b}: ${counts[i]} gaps`);
            g.appendChild(hit);
            s.appendChild(g);
        });
        s.appendChild(svg("line", { class: "dv-baseline", x1: left, x2: w - right, y1: top + plotH, y2: top + plotH }));
        return s;
    }
    function roundTop(x, y, w, h, r) {
        r = Math.min(r, h, w / 2);
        return `M${x},${y + h} L${x},${y + r} Q${x},${y} ${x + r},${y} L${x + w - r},${y} Q${x + w},${y} ${x + w},${y + r} L${x + w},${y + h} Z`;
    }
    function roundRight(x, y, w, h, r) {
        r = Math.min(r, w, h / 2);
        return `M${x},${y} L${x + w - r},${y} Q${x + w},${y} ${x + w},${y + r} L${x + w},${y + h - r} Q${x + w},${y + h} ${x + w - r},${y + h} L${x},${y + h} Z`;
    }

    function riskMatrix(r, container) {
        const w = widthOf(container, 300), cellGap = 3;
        const left = 74, top = 8, bottom = 40, rows = 5, cols = 3;
        const cellW = Math.min(64, (w - left - 10) / cols), cellH = 26;
        const h = top + rows * cellH + bottom;
        const grid = {};
        r.gaps.forEach(g => { const k = `${g.s}-${g.l}`; (grid[k] = grid[k] || []).push(g); });
        const maxCount = Math.max(1, ...Object.values(grid).map(v => v.length));
        const s = svg("svg", { class: "dv-chart", viewBox: `0 0 ${w} ${h}`, role: "group", "aria-label": "Risk matrix of severity by likelihood" });
        for (let sv = 5; sv >= 1; sv--) {
            const y = top + (5 - sv) * cellH;
            s.appendChild(svg("text", { class: "dv-axis-text", x: left - 8, y: y + cellH / 2 + 4, "text-anchor": "end", text: `Severity ${sv}` }));
            for (let lv = 1; lv <= 3; lv++) {
                const x = left + (lv - 1) * cellW;
                const items = grid[`${sv}-${lv}`] || [];
                const n = items.length;
                const step = n ? Math.min(RAMP.length - 1, Math.ceil(n / maxCount * RAMP.length) - 1) : -1;
                const fill = n ? cssVar(RAMP[step]) : cssVar("--dv-empty-cell");
                const cell = svg("rect", { x: x + cellGap / 2, y: y + cellGap / 2, width: cellW - cellGap, height: cellH - cellGap, rx: 4, fill });
                const g = svg("g", {}, [cell]);
                if (n) {
                    g.appendChild(svg("text", { x: x + cellW / 2, y: y + cellH / 2 + 4, "text-anchor": "middle", "font-size": "11.5", "font-weight": "700", fill: inkOn(fill), text: String(n) }));
                }
                const lines = [`Severity ${sv} × Likelihood ${lv}`, ["Gaps", n]].concat(items.slice(0, 4).map(it => `• ${truncate(it.gap, 48)} (${it.score})`));
                if (items.length > 4) lines.push(`+${items.length - 4} more`);
                bindTip(g, lines, `Severity ${sv}, likelihood ${lv}: ${n} gaps`);
                s.appendChild(g);
            }
        }
        for (let lv = 1; lv <= 3; lv++) {
            s.appendChild(svg("text", { class: "dv-axis-text", x: left + (lv - 0.5) * cellW, y: top + rows * cellH + 15, "text-anchor": "middle", text: String(lv) }));
        }
        s.appendChild(svg("text", { class: "dv-axis-text", x: left + 1.5 * cellW, y: top + rows * cellH + 32, "text-anchor": "middle", text: "Likelihood" }));
        return s;
    }

    function hBars(items, container, opts) {
        // items: [{label, value, tip, onClick}], largest first
        const w = widthOf(container, 300), barH = 16, gap = 10, labelW = opts.labelW || 118, top = 4, right = 34;
        const h = top + items.length * (barH + gap);
        const max = niceMax(Math.max(1, ...items.map(i => i.value)));
        const s = svg("svg", { class: "dv-chart", viewBox: `0 0 ${w} ${h}`, role: "group", "aria-label": opts.label });
        const plotW = w - labelW - right;
        items.forEach((it, i) => {
            const y = top + i * (barH + gap);
            const bw = Math.max(2, it.value / max * plotW);
            const g = svg("g");
            g.appendChild(svg("text", { class: "dv-cat-text", x: labelW - 8, y: y + barH / 2 + 4, "text-anchor": "end", text: truncate(it.label, opts.maxLabel || 18) }));
            g.appendChild(svg("path", { d: roundRight(labelW, y, bw, barH, 4), fill: it.color || cssVar(opts.colorVar || "--dv-bar") }));
            g.appendChild(svg("text", { class: "dv-value-text", x: labelW + bw + 6, y: y + barH / 2 + 4, text: String(it.value) }));
            const hit = svg("rect", { class: "dv-hit", x: 0, y: y - gap / 2, width: w, height: barH + gap });
            bindTip(hit, it.tip, `${it.label}: ${it.value}`);
            if (it.onClick) {
                hit.classList.add("dv-clickable");
                hit.addEventListener("click", it.onClick);
                hit.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); it.onClick(); } });
            }
            g.appendChild(hit);
            s.appendChild(g);
        });
        return s;
    }

    function gapsByStandard(r) {
        const counts = {};
        r.gaps.forEach(g => { const k = g.standard || "Unspecified"; counts[k] = counts[k] || { n: 0, score: 0 }; counts[k].n++; counts[k].score += g.score; });
        return Object.entries(counts)
            .map(([label, v]) => ({ label, value: v.n, score: v.score }))
            .sort((a, b) => b.value - a.value || b.score - a.score || a.label.localeCompare(b.label));
    }

    // Monotone cubic interpolation: the curve never overshoots a data point.
    function monotonePath(pts) {
        if (pts.length < 2) return "";
        if (pts.length === 2) return `M${pts[0][0]},${pts[0][1]} L${pts[1][0]},${pts[1][1]}`;
        const n = pts.length, dx = [], dy = [], m = [], t = [];
        for (let i = 0; i < n - 1; i++) { dx[i] = pts[i + 1][0] - pts[i][0]; dy[i] = pts[i + 1][1] - pts[i][1]; m[i] = dy[i] / dx[i]; }
        t[0] = m[0]; t[n - 1] = m[n - 2];
        for (let i = 1; i < n - 1; i++) t[i] = m[i - 1] * m[i] <= 0 ? 0 : (m[i - 1] + m[i]) / 2;
        for (let i = 0; i < n - 1; i++) {
            if (m[i] === 0) { t[i] = 0; t[i + 1] = 0; continue; }
            const a = t[i] / m[i], b = t[i + 1] / m[i], k = a * a + b * b;
            if (k > 9) { const tau = 3 / Math.sqrt(k); t[i] = tau * a * m[i]; t[i + 1] = tau * b * m[i]; }
        }
        let d = `M${pts[0][0]},${pts[0][1]}`;
        for (let i = 0; i < n - 1; i++) {
            const h = dx[i] / 3;
            d += ` C${pts[i][0] + h},${pts[i][1] + t[i] * h} ${pts[i + 1][0] - h},${pts[i + 1][1] - t[i + 1] * h} ${pts[i + 1][0]},${pts[i + 1][1]}`;
        }
        return d;
    }

    function trendChart(container) {
        const list = riskReadable();
        const metric = state.trendMetric;
        const values = list.map(r => metric === "gaps" ? r.gaps.length : sum(r.gaps.map(g => g.score)));
        const w = widthOf(container, 520), h = 220, left = 38, right = 18, top = 26, bottom = 30;
        const max = niceMax(Math.max(1, ...values));
        const s = svg("svg", { class: "dv-chart", viewBox: `0 0 ${w} ${h}`, role: "group", "aria-label": metric === "gaps" ? "Gaps per evaluation" : "Total risk score per evaluation" });
        const plotW = w - left - right, plotH = h - top - bottom;
        const x = i => list.length === 1 ? left + plotW / 2 : left + i * plotW / (list.length - 1);
        const y = v => top + plotH - v / max * plotH;
        ticks(max).forEach(t => {
            s.appendChild(svg("line", { class: "dv-gridline", x1: left, x2: w - right, y1: y(t), y2: y(t) }));
            s.appendChild(svg("text", { class: "dv-axis-text", x: left - 6, y: y(t) + 4, "text-anchor": "end", text: String(t) }));
        });
        s.appendChild(svg("line", { class: "dv-baseline", x1: left, x2: w - right, y1: y(0), y2: y(0) }));
        const pts = values.map((v, i) => [x(i), y(v)]);
        const color = cssVar("--dv-bar");
        if (pts.length > 1) {
            const line = monotonePath(pts);
            const gradId = `dvTrendFill${metric}`;
            s.appendChild(svg("defs", {}, [svg("linearGradient", { id: gradId, x1: "0", y1: "0", x2: "0", y2: "1" }, [
                svg("stop", { offset: "0%", "stop-color": color, "stop-opacity": "0.28" }),
                svg("stop", { offset: "100%", "stop-color": color, "stop-opacity": "0.02" }),
            ])]));
            s.appendChild(svg("path", { d: `${line} L${pts[pts.length - 1][0]},${y(0)} L${pts[0][0]},${y(0)} Z`, fill: `url(#${gradId})` }));
            s.appendChild(svg("path", { d: line, fill: "none", stroke: color, "stroke-width": 2.5, "stroke-linecap": "round" }));
        }
        const labelEvery = Math.max(1, Math.ceil(list.length / Math.max(1, Math.floor(plotW / 64))));
        const cross = svg("line", { class: "dv-baseline", x1: 0, x2: 0, y1: top, y2: top + plotH, opacity: 0, "stroke-dasharray": "3 3" });
        s.appendChild(cross);
        list.forEach((r, i) => {
            const [px, py] = pts[i];
            const isSel = r.report_id === (selected() && selected().report_id);
            s.appendChild(svg("circle", { cx: px, cy: py, r: isSel ? 5.5 : 4, fill: isSel ? color : cssVar("--dv-surface"), stroke: color, "stroke-width": 2 }));
            if (i > 0) {
                const d = values[i] - values[i - 1];
                const txt = d === 0 ? "0" : `${d > 0 ? "+" : "−"}${Math.abs(d)}`;
                s.appendChild(svg("text", { class: "dv-axis-text", x: px, y: py - 10, "text-anchor": "middle", "font-weight": "700", text: txt }));
            }
            if (i % labelEvery === 0 || i === list.length - 1) {
                s.appendChild(svg("text", { class: "dv-axis-text", x: px, y: h - 10, "text-anchor": "middle", text: shortDate(r.timestamp) }));
            }
            const slotW = list.length === 1 ? plotW : plotW / (list.length - 1);
            const hit = svg("rect", { class: "dv-hit dv-clickable", x: px - slotW / 2, y: top, width: slotW, height: plotH });
            const tipLines = [fmtDate(r.timestamp, true), [metric === "gaps" ? "Gaps" : "Total risk score", values[i]]];
            if (i > 0) tipLines.push(["Change vs previous", (values[i] - values[i - 1] > 0 ? "+" : "") + (values[i] - values[i - 1])]);
            tipLines.push(`Standards: ${truncate((r.standards || []).join(", ") || "not recorded", 90)}`);
            tipLines.push("Click to view this evaluation");
            bindTip(hit, tipLines, `${fmtDate(r.timestamp)}: ${values[i]}`);
            hit.addEventListener("pointerenter", () => { cross.setAttribute("x1", px); cross.setAttribute("x2", px); cross.setAttribute("opacity", 1); });
            hit.addEventListener("pointerleave", () => cross.setAttribute("opacity", 0));
            const choose = () => { state.selectedId = r.report_id; render(); };
            hit.addEventListener("click", choose);
            hit.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(); } });
            s.appendChild(hit);
        });
        return s;
    }

    function coverageStacks(container) {
        const list = coverageReadable().slice(-8);
        const statuses = state.data.coverage_statuses;
        const w = widthOf(container, 420), h = 210, left = 30, right = 10, top = 14, bottom = 30;
        const totals = list.map(r => statuses.map(st => r.coverage.filter(c => c.status === st).length));
        const max = niceMax(Math.max(1, ...totals.map(t => sum(t))));
        const s = svg("svg", { class: "dv-chart", viewBox: `0 0 ${w} ${h}`, role: "group", "aria-label": "Standards coverage per evaluation" });
        const plotW = w - left - right, plotH = h - top - bottom;
        ticks(max).forEach(t => {
            const y = top + plotH - t / max * plotH;
            s.appendChild(svg("line", { class: "dv-gridline", x1: left, x2: w - right, y1: y, y2: y }));
            s.appendChild(svg("text", { class: "dv-axis-text", x: left - 6, y: y + 4, "text-anchor": "end", text: String(t) }));
        });
        const slot = plotW / Math.max(1, list.length), bw = Math.min(38, slot * 0.6);
        list.forEach((r, i) => {
            const x = left + slot * i + (slot - bw) / 2;
            let yCursor = top + plotH;
            totals[i].forEach((n, si) => {
                if (!n) return;
                const segH = n / max * plotH;
                const y = yCursor - segH;
                const fill = cssVar(STATUS_VAR[statuses[si]]);
                const rect = svg("rect", { x, y: y + 1, width: bw, height: Math.max(1, segH - 2), rx: 3, fill });
                bindTip(rect, [fmtDate(r.timestamp, true), [statuses[si], n], ["Standards assessed", sum(totals[i])]], `${shortDate(r.timestamp)}, ${statuses[si]}: ${n}`);
                s.appendChild(rect);
                if (segH >= 16) s.appendChild(svg("text", { x: x + bw / 2, y: y + segH / 2 + 4, "text-anchor": "middle", "font-size": "11", "font-weight": "700", fill: inkOn(fill), "pointer-events": "none", text: String(n) }));
                yCursor = y;
            });
            s.appendChild(svg("text", { class: "dv-axis-text", x: x + bw / 2, y: h - 10, "text-anchor": "middle", text: shortDate(r.timestamp) }));
        });
        s.appendChild(svg("line", { class: "dv-baseline", x1: left, x2: w - right, y1: top + plotH, y2: top + plotH }));
        return s;
    }
    function legend(entries) {
        return el("div", { class: "dv-legend" }, entries.map(([label, varName]) => {
            const sw = el("i");
            sw.style.background = cssVar(varName);
            return el("span", {}, [sw, document.createTextNode(label)]);
        }));
    }

    // ---------------------------------------------------------------- side panel
    function sidePanel(r) {
        const list = reports();
        const m = metrics(r);
        const unreadable = list.filter(x => !x.risk_table_found || !x.coverage_found || x.unparsed_rows > 0).length;
        const stats = el("div", { class: "dv-panel-stats" }, [
            ["Evaluations run", list.length],
            ["Standards assessed", m.assessed],
            ["Total risk score", m.totalScore],
            ["Scored gaps", m.gaps],
        ].map(([k, v]) => el("div", { class: "dv-stat" }, [el("span", { text: k }), el("b", { text: shown(v) })])));

        const top = r.gaps.slice().sort((a, b) => b.score - a.score).slice(0, 6);
        const chartHolder = el("div");
        const panel = el("aside", { class: "dv-panel", "aria-label": "Overview and top risks" }, [
            el("h3", { text: "Overview" }),
            el("p", { class: "dv-panel-note", text: `Evaluation of ${fmtDate(r.timestamp, true)}`, style: "margin:-0.3rem 0 0.7rem" }),
            stats,
            el("div", { class: "dv-panel-sep" }),
            el("h3", { text: "Top risks by score" }),
            chartHolder,
        ]);
        requestAnimationFrame(() => {
            if (!top.length) {
                chartHolder.appendChild(el("p", { class: "dv-panel-note", text: r.risk_table_found ? "No scored gaps in this evaluation." : "This report has no readable risk score table." }));
                return;
            }
            // Full gap names on their own line, so nothing is cut off.
            const max = niceMax(top[0].score);
            top.forEach(g => {
                const bar = el("div", { class: "dv-risk-bar" });
                bar.style.width = `${Math.max(2, g.score / max * 100)}%`;
                const row = el("div", { class: "dv-risk", role: "button", tabindex: "0" }, [
                    el("div", { class: "dv-risk-name", text: g.gap }),
                    el("div", { class: "dv-risk-track" }, [bar, el("span", { class: "dv-risk-score", text: String(g.score) })]),
                    el("div", { class: "dv-risk-meta", text: `${g.standard || "Unspecified"} · ${g.band}${g.escalated ? " (escalated)" : ""}` }),
                ]);
                const tip = [g.gap, ["Standard", g.standard || "Unspecified"], ["S × L × G", `${g.s} × ${g.l} × ${g.g} = ${g.score}`], ["Priority", g.band + (g.escalated ? " (escalated)" : "")], "Click to open the report"];
                row.addEventListener("pointerenter", e => showTip(e, tip));
                row.addEventListener("pointermove", e => showTip(e, tip));
                row.addEventListener("pointerleave", hideTip);
                row.addEventListener("focus", e => showTip(e, tip));
                row.addEventListener("blur", hideTip);
                row.setAttribute("aria-label", `${g.gap}, score ${g.score}, ${g.band}. Open the report.`);
                row.addEventListener("click", () => openReport(r));
                row.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openReport(r); } });
                chartHolder.appendChild(row);
            });
            chartHolder.appendChild(el("button", { class: "dv-link", type: "button", text: "Open full report →", onclick: () => openReport(r), style: "margin-top:0.4rem;padding-left:0" }));
        });
        if (unreadable) {
            panel.appendChild(el("div", { class: "dv-warn", text: `${unreadable} report(s) had a table that could not be fully read; their unreadable rows are left out rather than guessed.` }));
        }
        return panel;
    }
    function openReport(r) {
        if (typeof window.viewReport === "function") window.viewReport(r.report_id, { timestamp: r.timestamp, standards: r.standards });
    }

    // ---------------------------------------------------------------- render
    function header(r) {
        const list = reports();
        const select = el("select", { class: "dv-select", id: "dvReportSelect", "aria-label": "Evaluation shown" },
            list.slice().reverse().map((x, i) => el("option", { value: x.report_id, text: `${fmtDate(x.timestamp, true)}${i === 0 ? " (latest)" : ""}` })));
        select.value = r.report_id;
        select.addEventListener("change", () => { state.selectedId = select.value; render(); });
        const refresh = el("button", { class: "dv-btn", type: "button", onclick: () => load() }, [icon("refresh"), el("span", { text: "Refresh" })]);
        refresh.querySelector("svg").setAttribute("class", "icon");
        return el("div", { class: "dv-header" }, [
            el("div", {}, [
                el("h2", { class: "dv-title" }, [document.createTextNode("Compliance "), el("span", { text: "Dashboard" })]),
                el("div", { class: "dv-subtitle", text: "Figures are read from the tables in your saved evaluation reports." }),
            ]),
            el("div", { class: "dv-controls" }, [el("label", { for: "dvReportSelect", text: "Evaluation" }), select, refresh]),
        ]);
    }

    function render() {
        if (!root) return;
        hideTip();
        root.replaceChildren();
        tooltip = el("div", { class: "dv-tooltip", role: "tooltip" });
        if (state.loading && !state.data) { root.appendChild(el("div", { class: "dv-empty" }, [el("p", { text: "Loading dashboard…" })])); root.appendChild(tooltip); return; }
        if (state.error) {
            root.appendChild(el("div", { class: "dv-empty" }, [el("h3", { text: "Dashboard unavailable" }), el("p", { text: state.error })]));
            root.appendChild(tooltip);
            return;
        }
        const r = selected();
        if (!r) {
            root.appendChild(el("div", { class: "dv-empty" }, [
                el("h3", { text: "No evaluations yet" }),
                el("p", { text: "Run a compliance evaluation from the sidebar. Its gaps, risk scores and standards coverage will appear here." }),
            ]));
            root.appendChild(tooltip);
            return;
        }
        state.selectedId = r.report_id;

        const prioHolder = el("div"), matrixHolder = el("div"), stdHolder = el("div"), trendHolder = el("div"), covHolder = el("div");
        const stdItems = gapsByStandard(r);
        const bands = state.data.bands;
        const statuses = state.data.coverage_statuses;

        const trendSeg = el("div", { class: "dv-seg", role: "group", "aria-label": "Trend measure" }, [["gaps", "Gaps"], ["score", "Risk score"]].map(([k, label]) =>
            el("button", { type: "button", "aria-pressed": String(state.trendMetric === k), text: label, onclick: () => { state.trendMetric = k; render(); } })));

        const main = el("div", { class: "dv-main" }, [
            kpiRow(r),
            el("div", { class: "dv-grid-3" }, [
                card("Gaps by priority", "Number of scored gaps in each priority band", "prio", prioHolder,
                    () => table(["Priority band", "Gaps"], bands.map(b => [b, r.gaps.filter(g => g.band === b).length]), [1])),
                card("Risk matrix", "Gaps by severity and likelihood; stronger colour means more gaps", "matrix", matrixHolder,
                    () => table(["Gap", "Standard", "S", "L", "G", "Score"], r.gaps.map(g => [g.gap, g.standard, g.s, g.l, g.g, g.score]), [2, 3, 4, 5])),
                card("Gaps by standard", "Scored gaps per standard, most first", "std", stdHolder,
                    () => table(["Standard", "Gaps", "Total score"], stdItems.map(i => [i.label, i.value, i.score]), [1, 2])),
            ]),
            el("div", { class: "dv-grid-2" }, [
                card("Trend across evaluations", "Change labels compare each evaluation with the one before it", "trend", trendHolder,
                    () => table(["Evaluation", "Gaps", "Total risk score"], reports().map(x => x.risk_table_found ? [fmtDate(x.timestamp, true), x.gaps.length, sum(x.gaps.map(g => g.score))] : [fmtDate(x.timestamp, true), "\u2014", "\u2014"]), [1, 2]), [trendSeg]),
                card("Standards coverage", "Status of each assessed standard, last 8 evaluations", "cov", covHolder,
                    () => table(["Evaluation"].concat(statuses), coverageReadable().slice(-8).map(x => [fmtDate(x.timestamp)].concat(statuses.map(st => x.coverage.filter(c => c.status === st).length))), [1, 2, 3])),
            ]),
        ]);
        root.appendChild(header(r));
        root.appendChild(el("div", { class: "dv-layout" }, [main, sidePanel(r)]));
        root.appendChild(tooltip);

        // Charts need their containers' widths, so draw after layout.
        requestAnimationFrame(() => {
            const noRisk = "This report has no readable risk score table, so its gaps are not shown.";
            if (!state.tables.prio) {
                prioHolder.appendChild(r.risk_table_found ? priorityBars(r, prioHolder) : emptyNote(noRisk));
            }
            if (!state.tables.matrix) {
                matrixHolder.appendChild(!r.risk_table_found ? emptyNote(noRisk)
                    : r.gaps.length ? riskMatrix(r, matrixHolder) : emptyNote("No scored gaps in this evaluation."));
            }
            if (!state.tables.std) {
                stdHolder.appendChild(!r.risk_table_found ? emptyNote(noRisk) : stdItems.length ? hBars(stdItems.map(i => ({
                    label: i.label, value: i.value,
                    tip: [i.label, ["Gaps", i.value], ["Total risk score", i.score]],
                })), stdHolder, { label: "Gaps by standard", labelW: 118, maxLabel: 18 }) : emptyNote("No scored gaps in this evaluation."));
            }
            if (!state.tables.trend) {
                const readable = riskReadable().length, skipped = reports().length - readable;
                if (readable) trendHolder.appendChild(trendChart(trendHolder));
                if (readable === 1) trendHolder.appendChild(emptyNote("Run more evaluations to see a trend."));
                if (skipped) trendHolder.appendChild(emptyNote(`${skipped} evaluation(s) without a readable risk score table are not plotted.`));
            }
            if (!state.tables.cov) {
                const readable = coverageReadable().length, skipped = reports().length - readable;
                if (readable) {
                    covHolder.appendChild(coverageStacks(covHolder));
                    covHolder.appendChild(legend(statuses.map(st => [st, STATUS_VAR[st]])));
                }
                if (skipped) covHolder.appendChild(emptyNote(`${skipped} evaluation(s) without a readable coverage table are not shown.`));
            }
            if (!state.tables.prio && r.risk_table_found) prioHolder.appendChild(legend(bands.map(b => [b, BAND_VAR[b]])));
        });
    }

    async function load() {
        state.loading = true;
        state.error = null;
        if (!state.data) render();
        try {
            const res = await fetch("/dashboard/data");
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || "Could not load the dashboard.");
            state.data = data;
        } catch (e) {
            state.error = e.message || "Could not load the dashboard.";
        } finally {
            state.loading = false;
            render();
        }
    }

    function init(container) {
        if (root || !container) return;
        root = container;
        window.addEventListener("resize", () => {
            if (root.hidden) return;
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(render, 150);
        });
        // Theme changes swap the colour tokens; redraw so SVG fills follow.
        new MutationObserver(() => { if (!root.hidden && state.data) render(); })
            .observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
        if (window.matchMedia) {
            window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (!root.hidden && state.data) render(); });
        }
    }

    function ensureInit() {
        init(document.getElementById("dashboardView"));
        return !!root;
    }

    window.Dashboard = {
        init,
        show() { if (ensureInit()) load(); },
        // Called when reports change; reloads now if visible, otherwise on next show.
        refresh() { if (root && !root.hidden) load(); else state.data = null; },
    };

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ensureInit);
    else ensureInit();
})();
