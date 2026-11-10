import { useMemo, useState } from "react";
import {
  Activity, BarChart3, Bell, CandlestickChart, Clock3, Crosshair, Database, Filter, Gauge, Layers,
  LineChart, Radar, Rocket, Send, ShieldAlert, Sigma, Target, Timer, TrendingUp, Volume2, Waves,
} from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CONTEXT, STATUS, ago, big, pct, px, tzTime } from "../api";
import { Empty, Feed, Kpi, Panel, Pill, SetupCard, Sparkline } from "./ui";
import LiveChart from "./LiveChart";

const ACTIVE = ["pending", "triggered"];

/* ================= Overview ================= */
export function Overview({ status, events, now }) {
  const setups = status?.setups || [];
  const active = setups.filter((s) => ACTIVE.includes(s.status));
  const today = new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });
  const todays = events.filter((e) => (e.time || "").startsWith(today));
  const tg = status?.telegram || {};
  const ds = status?.data_stats || {};
  const closed = setups.filter((s) => ["target", "stopped"].includes(s.status));
  const wins = closed.filter((s) => s.status === "target").length;

  return (
    <>
      <div className="grid kpis">
        <Kpi icon={Radar} label="Stocks in scanner" value={status?.universe?.length ?? "—"}
          foot={`${status?.watchlist?.length || 0} from watchlist`} color="var(--blue)" />
        <Kpi icon={Crosshair} label="Active setups" value={active.length}
          foot={`${active.filter((s) => s.status === "pending").length} waiting · ${active.filter((s) => s.status === "triggered").length} triggered`} color="var(--amber)" />
        <Kpi icon={Bell} label="Alerts today" value={todays.length}
          foot={`${todays.filter((e) => e.event === "runner").length} runner heads-ups`} color="var(--violet)" />
        <Kpi icon={Target} label="Closed today" value={closed.length ? `${wins}/${closed.length}` : "—"}
          foot="target hits / closed setups" color="var(--green)" />
        <Kpi icon={Send} label="Telegram" value={tg.configured ? `${tg.sent || 0}` : "off"}
          foot={tg.configured ? `${tg.failed || 0} failed · last ok ${ago(tg.last_ok, now)}` : "printing to console"} color="var(--green)" />
        <Kpi icon={Database} label="Data source" value={status?.data_source === "tradingview" ? "TradingView" : "Yahoo"}
          foot={`${ds.tradingview || 0} TV · ${ds.yahoo || 0} Yahoo · ${ds.errors || 0} errors`} color="var(--orange)" />
      </div>

      <div className="section-title">Live setups</div>
      {active.length ? (
        <div className="grid setups">{active.map((s) => <SetupCard key={s.key} s={s} />)}</div>
      ) : (
        <Panel><Empty icon={Crosshair}>No setup is waiting for a breakout right now. The bot keeps scanning every {status?.interval_seconds || 45}s.</Empty></Panel>
      )}

      <div className="section-title">Market</div>
      <div className="grid two">
        <Panel title="Scanner" hint="top gainers that passed every filter">
          <UniverseTable rows={status?.universe || []} compact />
        </Panel>
        <Panel title="Latest alerts" hint="as sent to Telegram">
          <Feed events={events} now={now} limit={8} />
        </Panel>
      </div>
    </>
  );
}

/* ================= Scanner ================= */
function UniverseTable({ rows, compact }) {
  if (!rows.length) return <Empty icon={Radar}>No stock passes the scanner filters right now.</Empty>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Symbol</th><th className="r">Change</th><th className="r">Last</th>
            {!compact && <><th className="r">HOD</th><th className="r">LOD</th></>}
            <th className="r">Volume</th><th className="r">Float rot.</th><th className="r">Best run (1M)</th>
            {!compact && <><th className="r">Mkt cap (pre-move)</th><th>Source</th></>}
            <th>Setups</th><th>Intraday (5m)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.symbol}>
              <td><span className="sym">{r.symbol}</span> <span className="faint" style={{ fontSize: 11 }}>{r.exchange}</span></td>
              <td className="r num up">{pct(r.change_pct, 0)}</td>
              <td className="r num">{px(r.last ?? r.close)}</td>
              {!compact && <><td className="r num">{px(r.hod)}</td><td className="r num">{px(r.lod)}</td></>}
              <td className="r num">{big(r.day_volume)}</td>
              <td className="r num">{r.float_rotation ? `x${r.float_rotation.toFixed(0)}` : "—"}</td>
              <td className="r num" title={r.history?.date ? `on ${r.history.date}` : ""}>
                {r.history?.max_pct != null
                  ? <span className={r.history.max_pct >= 80 ? "up" : "muted"}>+{r.history.max_pct.toFixed(0)}% <span className="faint">{r.history.days_ago}d</span></span>
                  : "—"}
              </td>
              {!compact && <>
                <td className="r num">{r.market_cap ? `$${big(r.market_cap)}` : "—"}</td>
                <td><Pill tone={r.source === "watchlist" ? "violet" : "blue"}>{r.source}</Pill></td>
              </>}
              <td>{r.status === "error" ? <Pill tone="red">error</Pill>
                : r.active_setups ? <Pill tone="amber">{r.active_setups} active</Pill> : <span className="faint">—</span>}</td>
              <td><Sparkline data={r.spark} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Scanner({ status, config }) {
  const sc = config?.scanner || {};
  return (
    <>
      <div className="grid kpis" style={{ marginBottom: 16 }}>
        <Kpi icon={TrendingUp} label="Min daily gain" value={`${sc.min_change_pct ?? "—"}%`} foot="incl. premarket" color="var(--green)" />
        <Kpi icon={Layers} label="Max market cap" value={sc.max_market_cap ? `$${big(sc.max_market_cap)}` : "off"} foot="before today's move" color="var(--blue)" />
        <Kpi icon={Volume2} label="Min volume" value={big(sc.min_volume)} foot={`float rotation ≥ x${sc.min_float_rotation ?? "—"}`} color="var(--orange)" />
        <Kpi icon={Filter} label="Exchanges" value={(sc.exchanges || []).join(" · ") || "—"} foot={`top ${sc.max_symbols ?? "—"} symbols`} color="var(--violet)" />
      </div>
      <Panel title="Stocks being scanned" hint={`updated ${tzTime(status?.updated, undefined, { second: "2-digit" })} NY`}>
        <UniverseTable rows={status?.universe || []} />
      </Panel>
    </>
  );
}

/* ================= Setups ================= */
export function Setups({ status }) {
  const [filter, setFilter] = useState("active");
  const all = status?.setups || [];
  const list = all.filter((s) => filter === "all" || (filter === "active" ? ACTIVE.includes(s.status) : s.status === filter));
  const counts = useMemo(() => Object.fromEntries(Object.keys(STATUS).map((k) => [k, all.filter((s) => s.status === k).length])), [all]);
  return (
    <>
      <div className="tabs" style={{ marginBottom: 16 }}>
        {[["active", "Active", all.filter((s) => ACTIVE.includes(s.status)).length], ["all", "All today", all.length],
          ...Object.entries(STATUS).map(([k, v]) => [k, v.label, counts[k]])].map(([k, label, n]) => (
          <button key={k} className={`tab${filter === k ? " active" : ""}`} onClick={() => setFilter(k)}>
            {label} <span className="faint">{n}</span>
          </button>
        ))}
      </div>
      {list.length ? <div className="grid setups">{list.map((s) => <SetupCard key={s.key} s={s} />)}</div>
        : <Panel><Empty icon={Crosshair}>Nothing here yet. Every setup the bot alerts on today shows up on this page and follows it to the end.</Empty></Panel>}
    </>
  );
}

/* ================= Alerts ================= */
export function Alerts({ events, now }) {
  const [type, setType] = useState("all");
  const types = ["all", ...new Set(events.map((e) => e.event))];
  const list = type === "all" ? events : events.filter((e) => e.event === type);
  return (
    <>
      <div className="tabs" style={{ marginBottom: 16 }}>
        {types.map((t) => (
          <button key={t} className={`tab${type === t ? " active" : ""}`} onClick={() => setType(t)}>
            {t === "all" ? "All" : t} <span className="faint">{t === "all" ? events.length : events.filter((e) => e.event === t).length}</span>
          </button>
        ))}
      </div>
      <Panel title="Alert history" hint="newest first · every message the bot sent">
        <Feed events={list} now={now} />
      </Panel>
    </>
  );
}

/* ================= Strategy ================= */
function Rule({ icon: Icon, tone, title, children, kv }) {
  return (
    <div className="panel rule">
      <div className="rule-h"><div className={`rule-icon t-${tone}`}><Icon size={18} /></div><h4>{title}</h4></div>
      <p>{children}</p>
      {kv && <div className="kv">{kv.filter(Boolean).map(([k, v]) => <div key={k}><span>{k}</span><b>{v}</b></div>)}</div>}
    </div>
  );
}

export function Strategy({ config: c }) {
  if (!c) return <Panel><Empty>Loading rules…</Empty></Panel>;
  const ib = c.inside_bar, tr = c.trend, tl = c.trendline, lv = c.levels, ex = c.extension, wk = c.wicks || {};
  return (
    <>
      <div className="banner warn" style={{ color: "var(--text)" }}>
        <ShieldAlert size={18} color="var(--amber)" />
        <span>Every number below is live from <b className="mono">config.yaml</b>. Change it there and the bot uses it on its next restart.</span>
      </div>
      <div className="section-title" style={{ marginTop: 0 }}>1 · Universe</div>
      <div className="grid rules">
        <Rule icon={Radar} tone="blue" title="Top gainers scanner" kv={[
          ["Exchanges", c.scanner.exchanges.join(", ")], ["Min daily gain", `${c.scanner.min_change_pct}%`],
          ["Max market cap (pre-move)", c.scanner.max_market_cap ? `$${big(c.scanner.max_market_cap)}` : "off"],
          ["Min day volume", big(c.scanner.min_volume)], ["Min float rotation", `x${c.scanner.min_float_rotation}`]]}>
          Stocks that already ran hard today, so a big % move is likely. Market cap is measured before today's
          move. Float rotation filters out heavy stocks with "no volume".
        </Rule>
        <Rule icon={Rocket} tone="violet" title="Runner heads-up" kv={[
          ["Alert when a stock first passes", `${c.alerts?.runner_alert_pct}%`],
          ["Same-stock cooldown", `${c.alerts?.symbol_cooldown_minutes} min`]]}>
          A stock that suddenly runs (from nowhere or on news) gets one message per day, before any setup,
          so you can get ready for the first pullback on the 1-minute chart.
        </Rule>
        <Rule icon={Clock3} tone="gray" title="Sessions" kv={[
          ["Scanning", "04:00 – 20:00 NY (all sessions joined)"],
          ...(c.session?.no_entry_windows || []).map(([a, b]) => ["No entries", `${a} – ${b} NY`]),
          ["Loop", `every ${c.loop.interval_seconds}s`]]}>
          Pre-market, regular and after-hours charts are joined. No entries in the first 15 minutes after
          the open; a setup may still form there.
        </Rule>
      </div>

      <div className="section-title">2 · Trigger – the inside bar</div>
      <div className="grid rules">
        <Rule icon={CandlestickChart} tone="amber" title="Inside bar" kv={[
          ["Timeframes", c.data.timeframes.map((t) => `${t}m`).join(" · ")], ["Entry", "above the mother bar high"],
          ["Stop", "low of the inside bar"], ["Target", `${ib.reward_risk}R (always)`],
          ["Min target", `+${ib.min_target_pct}%`], ["Mother bar max share of the run", `${Math.round(ib.max_mother_of_run * 100)}%`]]}>
          The mother bar engulfs the next bar including wicks: a short pause of a few bars before the next
          leg. A target above the day's high is still sent, with a warning.
        </Rule>
        <Rule icon={Timer} tone="gray" title="Validity & cancel" kv={[
          ["Valid for", `${ib.valid_bars} bars of the same timeframe`],
          ["Cancel on a close below", `stop − ${ib.stop_break_buffer_pct}%`],
          ib.support_hold && ["…or under a support zone", `${ib.support_hold.min_touches}+ lows within ${ib.support_hold.max_gap_pct}% under the stop`]]}>
          A small dip under the stop is not a strong break. When many bars found support just under the stop,
          the setup stays alive until that zone breaks too.
        </Rule>
        <Rule icon={Waves} tone="red" title="Sellers at the entry" kv={[
          ["Look back", `${wk.lookback_bars} bars`], ["At the level", `±${wk.level_tolerance_pct}%`],
          ["Upper wick ≥", `${Math.round((wk.min_wick_share || 0) * 100)}% of the bar`], ["Reject at", `${wk.max_rejections}+ such bars`]]}>
          Several bars that reach the entry level and close far below it leave upper wicks: sellers are
          defending the level, a bad sign for the entry.
        </Rule>
      </div>

      {c.overhead && (
        <div className="grid rules" style={{ marginTop: 16 }}>
          {c.range && <Rule icon={Waves} tone="gray" title="No sideways range" kv={[
            ["Band", `≤ ${c.range.band_pct}%`], ["Rejected after", `${c.range.max_minutes} min inside it`]]}>
            A stock that drifted sideways for a long time with no direction is not a setup – the
            inside bar there is noise, not a pause before the next leg.
          </Rule>}
          <Rule icon={ShieldAlert} tone="red" title="Room to run" kv={[
            ["Blocked if a level sits within", `${c.overhead.within_r}R above the entry`],
            ["Levels that block", "round numbers, premarket high"],
            ["A value zone must be", "at the entry or below it"],
            ["Trendline entry", "at the break of the line, never under it"]]}>
            A strong level right over the entry (like 0.30 over a 0.29 entry) is resistance, not a
            breakout – the move has no room before it hits sellers.
          </Rule>
        </div>
      )}

      <div className="section-title">3 · Context – at least one is required</div>
      <div className="grid rules">
        <Rule icon={TrendingUp} tone="green" title={CONTEXT.continuation.label} kv={[
          ["Structure", "higher lows, last one not broken"],
          ["Healthy pullback", `≤ ${Math.round(tr.max_pullback_of_run * 100)}% of the run (hard max ${Math.round(tr.hard_max_pullback_of_run * 100)}%)`],
          ["SMA touch", `SMA${tr.sma_length} within ${tr.sma_touch_tolerance_pct}% in the last ${tr.sma_touch_lookback_bars} bars`]]}>
          A healthy correction (about a third of a 90% run) to the moving average, measured on the setup's
          own timeframe.
        </Rule>
        <Rule icon={LineChart} tone="violet" title={CONTEXT.trendline_break.label} kv={[
          ["Touches", `${tl.min_touches}+ separate swing highs`], ["Line may sit above the entry", `up to ${tl.max_line_above_entry_pct}%`]]}>
          A real falling resistance line from the high of day. A steep fade right after a spike does not count.
        </Rule>
        <Rule icon={Layers} tone="orange" title={CONTEXT.level_break.label} kv={[
          ["Intraday zones", lv.include_intraday_zones ? `${lv.min_touches}+ highs within ${lv.cluster_pct}%` : "off (0/19 in backtest)"],
          ["Premarket high", lv.include_premarket_high ? "yes" : "no"],
          ["Daily chart levels", lv.include_daily_levels ? "swing highs/lows + yesterday" : "no"],
          ["Round numbers", lv.include_round_numbers ? "$1, half dollars, whole dollars…" : "no"]]}>
          The entry takes out a daily-chart level, a round number or the premarket high – for example $1.00.
          On its own (no uptrend, no downtrend line) it must come from above the base built after the high.
        </Rule>
      </div>

      <div className="section-title">4 · Filters & score</div>
      <div className="grid rules">
        <Rule icon={Gauge} tone="blue" title="Not extended" kv={Object.entries(ex.max_pct).map(([tf, v]) => [`${tf}m chart`, `≤ ${v}% above SMA${ex.sma_length}`])
          .concat([["Premarket", `ignores ${ex.premarket_ignore.join(", ")}m`]])}>
          Stay close to the average so there is room for another leg. The 15-minute chart may be more
          stretched; in premarket its pullback comes later.
        </Rule>
        <Rule icon={Activity} tone="green" title="Volume" kv={[
          ["Breakout vs avg", `${c.volume.avg_length}-bar average`], ["Or vs pullback", `x${c.volume.spike_vs_pullback}`],
          ["Premarket", "from TradingView feed"]]}>
          You want volume growing on the breakout; a quieter pullback is fine.
        </Rule>
        <Rule icon={Sigma} tone="amber" title="Quality score 0–100">
          Inside bar position in the mother bar, strength of the context (two contexts score higher),
          SMA touch, how close the entry is to the high of day, daily levels in the way, size of
          today's gain, breakout volume, and big runs in the last month (80–200% days = runs again).
          The score ranks setups – it never blocks one.
        </Rule>
      </div>
    </>
  );
}

/* ================= Backtest ================= */
export function Backtest({ backtest }) {
  const rows = backtest?.rows || [], sum = backtest?.summary || [];
  const chart = sum.map((r) => ({ name: `${r.tf}m ${CONTEXT[r.kind]?.label.split(" ")[0] || r.kind}`, R: r.total_r, wr: r.win_rate }));
  if (!rows.length) return <Panel><Empty icon={BarChart3}>No backtest yet. Run: <span className="mono">py backtest.py --days 10</span></Empty></Panel>;
  return (
    <>
      <div className="grid two">
        <Panel title="Total R by timeframe & context" hint="target = +2R, stop = −1R">
          <div style={{ height: 280 }}>
            <ResponsiveContainer>
              <BarChart data={chart} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
                <CartesianGrid stroke="var(--border)" vertical={false} />
                <XAxis dataKey="name" tick={{ fill: "var(--muted)", fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: "var(--muted)", fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip cursor={{ fill: "rgba(255,255,255,.03)" }}
                  contentStyle={{ background: "var(--panel-2)", border: "1px solid var(--border)", borderRadius: 10, color: "var(--text)" }} />
                <Bar dataKey="R" radius={[6, 6, 0, 0]}>
                  {chart.map((d, i) => <Cell key={i} fill={d.R >= 0 ? "var(--green)" : "var(--red)"} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>
        <Panel title="Summary" hint="small sample – a direction, not a conclusion">
          <div className="table-wrap">
            <table>
              <thead><tr><th>TF</th><th>Context</th><th className="r">Setups</th><th className="r">Triggered</th><th className="r">Win rate</th><th className="r">R</th></tr></thead>
              <tbody>
                {sum.map((r, i) => (
                  <tr key={i}>
                    <td className="num">{r.tf}m</td>
                    <td><Pill tone={CONTEXT[r.kind]?.tone || "gray"}>{CONTEXT[r.kind]?.label || r.kind}</Pill></td>
                    <td className="r num">{r.setups}</td><td className="r num">{r.triggered}</td>
                    <td className="r num">{r.win_rate == null ? "—" : `${Math.round(r.win_rate * 100)}%`}</td>
                    <td className={`r num ${r.total_r >= 0 ? "up" : "down"}`}>{r.total_r > 0 ? "+" : ""}{r.total_r}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
      <div className="section-title">Every setup in the backtest</div>
      <Panel pad={false}>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Symbol</th><th>Date</th><th>TF</th><th>Context</th><th>Inside bar</th><th className="r">Entry</th><th className="r">Stop</th><th className="r">Target</th><th className="r">Score</th><th>Outcome</th></tr></thead>
            <tbody>
              {rows.slice(0, 400).map((r, i) => (
                <tr key={i}>
                  <td className="sym">{r.symbol}</td><td className="num muted">{String(r.date).slice(0, 10)}</td>
                  <td className="num">{r.tf}m</td><td><Pill tone={CONTEXT[r.kind]?.tone || "gray"}>{CONTEXT[r.kind]?.label || r.kind}</Pill></td>
                  <td className="num">{r.inside}</td><td className="r num">{px(r.entry)}</td><td className="r num down">{px(r.stop)}</td>
                  <td className="r num up">{px(r.target)}</td><td className="r num">{r.score}</td>
                  <td><Pill tone={STATUS[r.status]?.tone || "gray"}>{STATUS[r.status]?.label || r.status}</Pill></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}

/* ================= Calibration ================= */
export function Calibration({ trades }) {
  return (
    <>
      <div className="banner warn" style={{ color: "var(--text)" }}>
        <Crosshair size={18} color="var(--amber)" />
        <span>Your own trades from <b className="mono">my_trades.csv</b>. Run <b className="mono">py calibrate.py</b> to see whether the bot finds each one, and which rule rejects the ones it misses.</span>
      </div>
      <Panel title="My trades" hint="times in Israel time, as on TradingView">
        {trades?.length ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Symbol</th><th>Date</th><th>Time</th><th>TF</th><th className="r">Entry</th><th className="r">Stop</th><th className="r">Risk</th><th>Result</th><th>Note</th></tr></thead>
              <tbody>
                {trades.map((t, i) => (
                  <tr key={i}>
                    <td className="sym">{t.symbol}</td><td className="num muted">{t.date}</td><td className="num">{t.time}</td>
                    <td className="num">{t.timeframe ? `${t.timeframe}m` : "—"}</td>
                    <td className="r num">{px(t.entry)}</td><td className="r num down">{px(t.stop)}</td>
                    <td className="r num">{t.stop ? `${(((t.entry - t.stop) / t.entry) * 100).toFixed(1)}%` : "—"}</td>
                    <td>{t.result ? <Pill tone={STATUS[t.result]?.tone || "gray"}>{t.result}</Pill> : "—"}</td>
                    <td className="muted" style={{ whiteSpace: "normal" }}>{t.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty icon={Crosshair}>No trades yet. Add rows to my_trades.csv or send a screenshot.</Empty>}
      </Panel>
    </>
  );
}

/* ================= Health ================= */
export function Health({ status, now }) {
  const s = status || {};
  const up = s.started ? ago(s.started, now).replace(" ago", "") : "—";
  return (
    <>
      <div className="grid kpis">
        <Kpi icon={Activity} label="Process" value={s.alive ? "Running" : "Stopped"} foot={`pid ${s.pid ?? "—"} · up ${up}`} color={s.alive ? "var(--green)" : "var(--red)"} />
        <Kpi icon={Clock3} label="Scans" value={s.scans ?? "—"} foot={`last ${ago(s.updated, now)}`} color="var(--blue)" />
        <Kpi icon={Timer} label="Scan duration" value={s.scan_seconds != null ? `${s.scan_seconds}s` : "—"} foot={`interval ${s.interval_seconds ?? "—"}s`} color="var(--amber)" />
        <Kpi icon={Database} label="Data requests" value={(s.data_stats?.tradingview || 0) + (s.data_stats?.yahoo || 0)}
          foot={`${s.data_stats?.tradingview || 0} TradingView · ${s.data_stats?.yahoo || 0} Yahoo fallback`} color="var(--orange)" />
        <Kpi icon={Send} label="Telegram" value={s.telegram?.configured ? "Connected" : "Off"}
          foot={`${s.telegram?.sent || 0} sent · ${s.telegram?.failed || 0} failed`} color="var(--violet)" />
      </div>
      <div className="section-title">Errors</div>
      <Panel>
        {s.errors?.length ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Time (NY)</th><th>Where</th><th>Error</th></tr></thead>
              <tbody>{[...s.errors].reverse().map((e, i) => (
                <tr key={i}><td className="num">{tzTime(e.time, undefined, { second: "2-digit" })}</td><td className="sym">{e.where}</td><td className="muted" style={{ whiteSpace: "normal" }}>{e.error}</td></tr>
              ))}</tbody>
            </table>
          </div>
        ) : <Empty icon={Activity}>No errors since the bot started.</Empty>}
      </Panel>
    </>
  );
}

/* ================= Charts ================= */
export function Charts({ status }) {
  const setups = (status?.setups || []).filter((s) => ACTIVE.includes(s.status));
  const symbols = [...new Set([...setups.map((s) => s.symbol), ...(status?.universe || []).map((r) => r.symbol)])];
  const [sym, setSym] = useState(null);
  const [tf, setTf] = useState(5);
  const symbol = sym && symbols.includes(sym) ? sym : symbols[0];
  if (!symbol) return <Panel><Empty icon={LineChart}>No stock in the scanner right now.</Empty></Panel>;
  const mine = setups.filter((s) => s.symbol === symbol);
  const row = (status?.universe || []).find((r) => r.symbol === symbol);
  return (
    <>
      <div className="chart-tools">
        <div className="tabs">
          {symbols.map((x) => {
            const n = setups.filter((s) => s.symbol === x).length;
            return <button key={x} className={`tab${x === symbol ? " active" : ""}`} onClick={() => setSym(x)}>
              <b>{x}</b>{n > 0 && <span style={{ color: "var(--amber)" }}> ● {n}</span>}</button>;
          })}
        </div>
        <span style={{ flex: 1 }} />
        <div className="tabs">
          {[1, 3, 5, 15].map((t) => <button key={t} className={`tab${t === tf ? " active" : ""}`} onClick={() => setTf(t)}>{t}m</button>)}
        </div>
      </div>
      <Panel pad={false}>
        <LiveChart symbol={symbol} tf={tf} setups={mine} height={520} refreshMs={4000} />
      </Panel>
      <div className="grid kpis" style={{ marginTop: 16 }}>
        <Kpi icon={TrendingUp} label="Today" value={pct(row?.change_pct, 0)} foot={`last ${px(row?.last)}`} color="var(--green)" />
        <Kpi icon={Layers} label="Day range" value={`${px(row?.lod)} – ${px(row?.hod)}`} foot="low – high of day" color="var(--blue)" />
        <Kpi icon={Volume2} label="Volume" value={big(row?.day_volume)} foot={row?.float_rotation ? `float rotation x${row.float_rotation.toFixed(0)}` : ""} color="var(--orange)" />
        <Kpi icon={Rocket} label="Best run (1M)" value={row?.history?.max_pct != null ? `+${row.history.max_pct.toFixed(0)}%` : "—"}
          foot={row?.history?.date ? `on ${row.history.date}` : ""} color="var(--violet)" />
      </div>
      {mine.length > 0 && <>
        <div className="section-title">Active setups on {symbol}</div>
        <div className="grid setups">{mine.map((s) => <SetupCard key={s.key} s={s} />)}</div>
      </>}
    </>
  );
}

/* ================= P&L ================= */
const RESULT = {
  target: { label: "Target", tone: "blue" },
  stopped: { label: "Stop", tone: "red" },
  day_close: { label: "Day close", tone: "amber" },
  open: { label: "Open", tone: "green" },
  unknown: { label: "No data", tone: "gray" },
};
const usd = (n, sign = false) => n == null ? "—"
  : `${sign && n > 0 ? "+" : n < 0 ? "−" : ""}$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const dayLabel = (d) => new Date(`${d}T12:00:00`).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });

function saved(key, fallback) {
  try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
}
function save(key, v) {
  try { localStorage.setItem(key, v); } catch { /* private mode */ }
}

export function Pnl({ pnl }) {
  const [amount, setAmount] = useState(() => saved("pnl.amount", "1000"));
  const [mode, setMode] = useState(() => saved("pnl.mode", "fixed"));
  const [open, setOpen] = useState(null);
  const cap = Math.max(0, Number(String(amount).replace(/[^\d.]/g, "")) || 0);

  const { days, trades, total, balance } = useMemo(() => {
    // trades in the order they closed: with "reinvest" each one is sized at the balance so far
    const list = (pnl?.trades || []).filter((t) => t.return_pct != null)
      .sort((a, b) => (a.exit_time || a.trigger_time).localeCompare(b.exit_time || b.trigger_time));
    let bal = cap;
    const rows = list.map((t) => {
      const size = mode === "compound" ? bal : cap;
      const usdPnl = (size * t.return_pct) / 100;
      bal += usdPnl;
      return { ...t, size, usd: usdPnl, after: bal };
    });
    const byDay = {};
    for (const t of rows) {
      const d = (byDay[t.day] ||= { day: t.day, trades: [], usd: 0, pct: 0, wins: 0, losses: 0 });
      d.trades.push(t); d.usd += t.usd; d.pct += t.return_pct;
      if (t.return_pct > 0) d.wins += 1; else if (t.return_pct < 0) d.losses += 1;
      d.balance = t.after;
    }
    return { days: Object.values(byDay).sort((a, b) => b.day.localeCompare(a.day)), trades: rows,
      total: bal - cap, balance: bal };
  }, [pnl, cap, mode]);

  if (!pnl) return <Panel><Empty icon={Sigma}>Loading…</Empty></Panel>;
  if (!pnl.trades.length) return <Panel><Empty icon={Sigma}>No setup has broken out yet – nothing to count.</Empty></Panel>;

  const wins = trades.filter((t) => t.return_pct > 0).length;
  const chart = [...days].reverse().map((d) => ({ name: dayLabel(d.day), usd: Math.round(d.usd * 100) / 100 }));
  const onAmount = (v) => { setAmount(v); save("pnl.amount", v); };
  const onMode = (v) => { setMode(v); save("pnl.mode", v); };

  return (
    <>
      <div className="panel pnl-input">
        <label>
          <small>{mode === "compound" ? "Starting balance" : "Amount per trade"}</small>
          <div className="money"><span>$</span>
            <input inputMode="decimal" value={amount} onChange={(e) => onAmount(e.target.value)} aria-label="Amount in dollars" />
          </div>
        </label>
        <div>
          <small>Position size</small>
          <div className="tabs">
            <button className={`tab${mode === "fixed" ? " active" : ""}`} onClick={() => onMode("fixed")}>Same amount every trade</button>
            <button className={`tab${mode === "compound" ? " active" : ""}`} onClick={() => onMode("compound")}>Reinvest (whole balance)</button>
          </div>
        </div>
        <div className="pnl-result">
          <small>Would have become</small>
          <b className={total >= 0 ? "up" : "down"}>{usd(balance)}</b>
          <span className={total >= 0 ? "up" : "down"}>{usd(total, true)} · {cap ? pct((total / cap) * 100) : "—"}</span>
        </div>
      </div>

      <div className="grid kpis" style={{ marginTop: 16 }}>
        <Kpi icon={TrendingUp} label="Total P&L" value={usd(total, true)} foot={`on ${usd(cap)}${mode === "fixed" ? " per trade" : " start"}`}
          color={total >= 0 ? "var(--green)" : "var(--red)"} />
        <Kpi icon={Target} label="Win rate" value={trades.length ? `${Math.round((wins / trades.length) * 100)}%` : "—"}
          foot={`${wins} won · ${trades.length - wins} lost`} color="var(--blue)" />
        <Kpi icon={Activity} label="Trades" value={trades.length} foot={`over ${days.length} day${days.length === 1 ? "" : "s"}`} color="var(--violet)" />
        <Kpi icon={Sigma} label="Sum of returns" value={pct(trades.reduce((s, t) => s + t.return_pct, 0))}
          foot="every trade's % added up" color="var(--orange)" />
      </div>

      <div className="grid two" style={{ marginTop: 16 }}>
        <Panel title="By day" hint="click a day for its trades">
          <div className="table-wrap">
            <table>
              <thead><tr><th>Day</th><th className="r">Trades</th><th className="r">Won / lost</th><th className="r">Sum %</th><th className="r">P&L</th><th className="r">Balance</th></tr></thead>
              <tbody>
                {days.map((d) => (
                  <tr key={d.day} className="click" onClick={() => setOpen(open === d.day ? null : d.day)}>
                    <td><b>{dayLabel(d.day)}</b></td>
                    <td className="r num">{d.trades.length}</td>
                    <td className="r num"><span className="up">{d.wins}</span> / <span className="down">{d.losses}</span></td>
                    <td className={`r num ${d.pct >= 0 ? "up" : "down"}`}>{pct(d.pct)}</td>
                    <td className={`r num ${d.usd >= 0 ? "up" : "down"}`}><b>{usd(d.usd, true)}</b></td>
                    <td className="r num">{usd(d.balance)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
        <Panel title="P&L per day" hint={`with ${usd(cap)}`}>
          <div style={{ height: 260 }}>
            <ResponsiveContainer>
              <BarChart data={chart} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                <CartesianGrid stroke="var(--border)" vertical={false} />
                <XAxis dataKey="name" tick={{ fill: "var(--muted)", fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: "var(--muted)", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v) => `$${v}`} />
                <Tooltip cursor={{ fill: "rgba(255,255,255,.03)" }} formatter={(v) => [usd(v, true), "P&L"]}
                  contentStyle={{ background: "var(--panel-2)", border: "1px solid var(--border)", borderRadius: 10, color: "var(--text)" }} />
                <Bar dataKey="usd" radius={[6, 6, 0, 0]}>
                  {chart.map((d, i) => <Cell key={i} fill={d.usd >= 0 ? "var(--green)" : "var(--red)"} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>
      </div>

      {days.filter((d) => !open || d.day === open).map((d) => (
        <div key={d.day}>
          <div className="section-title">{dayLabel(d.day)} · <span className={d.usd >= 0 ? "up" : "down"}>{usd(d.usd, true)}</span></div>
          <Panel pad={false}>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Symbol</th><th>TF</th><th>Context</th><th>Breakout</th><th className="r">Entry</th><th className="r">Exit</th><th>Result</th><th className="r">Return</th><th className="r">Size</th><th className="r">P&L</th></tr></thead>
                <tbody>
                  {d.trades.map((t) => (
                    <tr key={t.key}>
                      <td className="sym">{t.symbol}</td><td className="num">{t.timeframe}m</td>
                      <td><Pill tone={CONTEXT[t.kind]?.tone || "gray"}>{CONTEXT[t.kind]?.label || t.kind}</Pill></td>
                      <td className="num">{tzTime(t.trigger_time)}</td>
                      <td className="r num">{px(t.entry)}</td><td className="r num">{px(t.exit)}</td>
                      <td><Pill tone={RESULT[t.result]?.tone || "gray"}>{RESULT[t.result]?.label || t.result}</Pill>
                        {t.simulated && <span className="faint" title="The bot stopped following this stock – the result is worked out from 1-minute bars"> *</span>}</td>
                      <td className={`r num ${t.return_pct >= 0 ? "up" : "down"}`}>{pct(t.return_pct)}</td>
                      <td className="r num muted">{usd(t.size)}</td>
                      <td className={`r num ${t.usd >= 0 ? "up" : "down"}`}><b>{usd(t.usd, true)}</b></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>
      ))}

      <p className="faint" style={{ fontSize: 12.5, marginTop: 14, lineHeight: 1.6 }}>
        Every setup that broke out, bought at its entry and sold at the stop or the 2R target – no commissions or slippage, NY time.
        * the bot stopped following that stock, so the stop/target is found on 1-minute bars; if neither was hit the trade is
        closed at the day's last price (“Day close”) or marked at the latest price while it's still running (“Open”).
        “Reinvest” puts the whole balance in each trade in the order they closed, even when trades overlapped.
      </p>
    </>
  );
}
