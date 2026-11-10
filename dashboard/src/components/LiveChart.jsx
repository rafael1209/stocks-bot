import { useEffect, useRef, useState } from "react";
import { createChart, CrosshairMode, LineStyle } from "lightweight-charts";
import { px } from "../api";

/** NY wall-clock seconds from an ISO time like 2026-11-02T11:51:00-05:00 (charts place candles this way). */
export const wall = (iso) => (iso ? Date.parse(iso.slice(0, 19) + "Z") / 1000 : null);
const insideT = (s) => s.inside_wall ?? wall(s.inside_time);
const motherT = (s) => s.mother_wall ?? wall(s.mother_time);

const C = {
  bg: "#121823", grid: "#1a2130", text: "#8b95a9", border: "#212a3a",
  up: "#22c55e", down: "#f05252", sma: "#4c8dff", entry: "#22c55e", stop: "#f05252",
  target: "#4c8dff", level: "#ff8a3d", line: "#a78bfa", hod: "#f5a524",
};

/**
 * Live candlestick chart (TradingView Lightweight Charts).
 * Polls /api/bars every `refreshMs`; draws SMA10, volume and – when `setups` are given –
 * entry / stop / target / value zone, the downtrend line and mother+inside bar markers.
 */
export default function LiveChart({ symbol, tf = 5, setups = [], height = 340, refreshMs = 5000, showLegend = true,
                                   position = true, focusTime = null }) {
  const box = useRef(null);
  const api = useRef({});
  const fitted = useRef(false);
  const setupsRef = useRef(setups);
  const [last, setLast] = useState(null);
  const [shapes, setShapes] = useState([]);
  setupsRef.current = setups;

  /** Long-position boxes + mother/inside highlight, in pixel space (re-run on zoom/scroll/resize/data). */
  const relayout = () => {
    const { chart, candles } = api.current;
    if (!chart || !position) return setShapes([]);
    const ts = chart.timeScale();
    const plotW = box.current.clientWidth - chart.priceScale("right").width();
    const bs = ts.options().barSpacing;
    const bucket = (t) => t - (t % (tf * 60));
    const out = [];
    setupsRef.current.forEach((s, k) => {
      const yE = candles.priceToCoordinate(s.entry), yS = candles.priceToCoordinate(s.stop), yT = candles.priceToCoordinate(s.target);
      if (yE == null || yS == null || yT == null) return;
      const ti = insideT(s);
      if (!ti) return;
      let x1 = ts.timeToCoordinate(bucket(ti));
      if (x1 == null) return;
      x1 += bs / 2;
      const x2 = Math.min(plotW, x1 + Math.max(18 * bs, 170));
      if (x2 <= x1 + 4) return;
      out.push({ kind: "reward", k, left: x1, width: x2 - x1, top: yT, height: yE - yT, s });
      out.push({ kind: "risk", k, left: x1, width: x2 - x1, top: yE, height: yS - yE, s });
      if (s.timeframe === tf) {
        const xm = ts.timeToCoordinate(bucket(motherT(s))), xi = ts.timeToCoordinate(bucket(ti));
        if (xm != null && xi != null) out.push({ kind: "bars", k, left: xm - bs / 2 - 2, width: xi - xm + bs + 4, s });
      }
    });
    setShapes(out);
  };
  const [error, setError] = useState(null);

  // build the chart once per symbol/timeframe
  useEffect(() => {
    const chart = createChart(box.current, {
      height,
      layout: { background: { color: C.bg }, textColor: C.text, fontFamily: "Inter, system-ui, sans-serif", fontSize: 11 },
      grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } },
      rightPriceScale: { borderColor: C.border, scaleMargins: { top: 0.08, bottom: 0.24 } },
      timeScale: { borderColor: C.border, timeVisible: true, secondsVisible: false, rightOffset: 6, barSpacing: 7 },
      crosshair: { mode: CrosshairMode.Normal,
        vertLine: { color: "#3a465c", labelBackgroundColor: "#2b364a" },
        horzLine: { color: "#3a465c", labelBackgroundColor: "#2b364a" } },
      localization: { priceFormatter: (p) => px(p) },
      autoSize: true,
    });
    const candles = chart.addCandlestickSeries({
      upColor: C.up, downColor: C.down, borderUpColor: C.up, borderDownColor: C.down,
      wickUpColor: C.up, wickDownColor: C.down, priceFormat: { type: "price", precision: 4, minMove: 0.0001 },
    });
    const volume = chart.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    const smaLine = chart.addLineSeries({ color: C.sma, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    api.current = { chart, candles, volume, smaLine, lines: [], extra: [] };
    fitted.current = false;
    const relay = () => requestAnimationFrame(relayout);
    chart.timeScale().subscribeVisibleLogicalRangeChange(relay);
    const ro = new ResizeObserver(relay);
    ro.observe(box.current);
    return () => { ro.disconnect(); chart.remove(); api.current = {}; };
  }, [symbol, tf, height]);

  // setup overlays: price lines, trendline, markers
  useEffect(() => {
    const { chart, candles } = api.current;
    if (!chart) return;
    api.current.lines.forEach((l) => candles.removePriceLine(l));
    api.current.extra.forEach((s) => chart.removeSeries(s));
    api.current.lines = []; api.current.extra = [];
    const markers = [];
    setups.forEach((s, k) => {
      const tag = setups.length > 1 ? ` ${s.timeframe}m` : "";
      const add = (price, color, title, style = LineStyle.Dashed) => price != null &&
        api.current.lines.push(candles.createPriceLine({ price, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title: title + tag }));
      add(s.entry, C.entry, "Entry", LineStyle.Solid);
      add(s.stop, C.stop, position ? "" : "Stop");
      add(s.target, C.target, position ? "" : "Target 2R");
      if (s.level != null && Math.abs(s.level - s.entry) / s.entry > 0.002) add(s.level, C.level, "Zone", LineStyle.Dotted);
      if (s.trendline) {
        const ln = chart.addLineSeries({ color: C.line, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
        const end = insideT(s) + s.timeframe * 60 * 12;
        const slope = (s.trendline.p2 - s.trendline.p1) / (s.trendline.t2 - s.trendline.t1);
        ln.setData([{ time: s.trendline.t1, value: s.trendline.p1 }, { time: end, value: s.trendline.p1 + slope * (end - s.trendline.t1) }]);
        api.current.extra.push(ln);
      }
      if (!position && s.timeframe === tf && motherT(s)) {
        markers.push({ time: motherT(s) - (motherT(s) % (tf * 60)), position: "belowBar", color: "#f5a524", shape: "arrowUp", text: k === 0 ? "M" : "" });
        markers.push({ time: insideT(s) - (insideT(s) % (tf * 60)), position: "belowBar", color: "#f5a524", shape: "arrowUp", text: k === 0 ? "IB" : "" });
      }
    });
    candles.setMarkers(markers.sort((a, b) => a.time - b.time));
    requestAnimationFrame(relayout);
  }, [setups, tf, symbol]);

  // live data
  useEffect(() => {
    let alive = true, timer;
    const load = async () => {
      try {
        const r = await fetch(`/api/bars?symbol=${encodeURIComponent(symbol)}&tf=${tf}`, { cache: "no-store" });
        if (!r.ok) throw new Error(`${r.status}`);
        const d = await r.json();
        if (!alive || !api.current.chart) return;
        const { candles, volume, smaLine, chart } = api.current;
        candles.setData(d.bars);
        volume.setData(d.bars.map((b) => ({ time: b.time, value: b.volume,
          color: b.close >= b.open ? "rgba(34,197,94,0.45)" : "rgba(240,82,82,0.45)" })));
        smaLine.setData(d.sma);
        if (!fitted.current && d.bars.length) {
          const n = d.bars.length;
          // centre on the setup (inside bar) when asked, otherwise show the latest bars
          const f = focusTime ? d.bars.findIndex((b) => b.time >= focusTime - (focusTime % (tf * 60))) : -1;
          const range = f >= 0 ? { from: Math.max(0, f - 45), to: f + 32 } : { from: Math.max(0, n - 90), to: n + 4 };
          chart.timeScale().setVisibleLogicalRange(range);
          fitted.current = true;
        }
        setLast(d.bars[d.bars.length - 1] || null);
        requestAnimationFrame(relayout);
        setError(null);
      } catch (e) {
        if (alive) setError(String(e.message || e));
      }
      if (alive) timer = setTimeout(load, refreshMs);
    };
    load();
    return () => { alive = false; clearTimeout(timer); };
  }, [symbol, tf, refreshMs]);

  const chg = last ? ((last.close - last.open) / last.open) * 100 : 0;
  return (
    <div className="live-chart">
      {showLegend && (
        <div className="lc-legend">
          <span className="sym">{symbol}</span>
          <span className="tf">{tf}m</span>
          {last && <>
            <span className="mono">O <b>{px(last.open)}</b></span>
            <span className="mono">H <b>{px(last.high)}</b></span>
            <span className="mono">L <b>{px(last.low)}</b></span>
            <span className="mono">C <b className={chg >= 0 ? "up" : "down"}>{px(last.close)}</b></span>
          </>}
          <span className="lc-live"><span className="dot" />{error ? "reconnecting…" : "LIVE"}</span>
        </div>
      )}
      <div style={{ position: "relative" }}>
        <div ref={box} style={{ height }} />
        <div className="lc-overlay">
          {shapes.map((sh, i) => {
            const s = sh.s;
            if (sh.kind === "bars") return (
              <div key={i} className="lc-bars" style={{ left: sh.left, width: sh.width }}>
                <span>Inside bar</span>
              </div>);
            const reward = sh.kind === "reward";
            return (
              <div key={i} className={`lc-box ${reward ? "lc-reward" : "lc-risk"}`}
                style={{ left: sh.left, width: sh.width, top: sh.top, height: Math.max(2, sh.height) }}>
                {reward
                  ? <span className={`lc-tag ${sh.height < 24 ? "lc-tag-above" : "lc-tag-top"}`}>Target {px(s.target)} <b>+{s.target_pct.toFixed(1)}%</b></span>
                  : <span className={`lc-tag ${sh.height < 24 ? "lc-tag-below" : "lc-tag-bottom"}`}>Stop {px(s.stop)} <b>−{s.risk_pct.toFixed(1)}%</b></span>}
                {reward && <span className="lc-entry">Entry {px(s.entry)} · R:R {((s.target - s.entry) / (s.entry - s.stop)).toFixed(1)}</span>}
              </div>);
          })}
        </div>
      </div>
    </div>
  );
}
