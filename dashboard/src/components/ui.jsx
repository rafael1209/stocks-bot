import { useState } from "react";
import {
  AlertTriangle, ArrowUpRight, Ban, CheckCircle2, Clock, Info, Rocket, Send, Target, XCircle, Zap,
} from "lucide-react";
import { CONTEXT, EVENT, STATUS, ago, pct, px, tzTime } from "../api";
import LiveChart, { wall } from "./LiveChart";

export const Pill = ({ tone = "gray", children, live, title }) => (
  <span className={`pill t-${tone}${live ? " live" : ""}`} title={title}>
    {live !== undefined && <span className="dot" />}
    {children}
  </span>
);

export function Panel({ title, hint, right, children, pad = true, className = "" }) {
  return (
    <section className={`panel ${className}`}>
      {title && (
        <div className="panel-h">
          <h3>{title}</h3>
          {hint && <span className="hint">{hint}</span>}
          <span className="spacer" />
          {right}
        </div>
      )}
      <div className={pad ? "panel-b" : ""}>{children}</div>
    </section>
  );
}

export function Kpi({ icon: Icon, label, value, foot, color = "var(--blue)" }) {
  return (
    <div className="panel kpi">
      <div className="glow" style={{ background: color }} />
      <div className="label"><Icon size={15} color={color} /> {label}</div>
      <div className="value">{value}</div>
      {foot && <div className="foot">{foot}</div>}
    </div>
  );
}

export function Empty({ icon: Icon = Info, children }) {
  return (
    <div className="empty">
      <Icon size={28} />
      <div>{children}</div>
    </div>
  );
}

export function Sparkline({ data, width = 110, height = 30 }) {
  if (!data || data.length < 2) return <span className="faint">—</span>;
  const min = Math.min(...data), max = Math.max(...data), span = max - min || 1;
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * width},${height - 2 - ((v - min) / span) * (height - 4)}`);
  const up = data[data.length - 1] >= data[0];
  const color = up ? "var(--green)" : "var(--red)";
  const id = `g${Math.round(Math.random() * 1e9)}`;
  return (
    <svg width={width} height={height} style={{ display: "block" }}>
      <defs>
        <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.28" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={`0,${height} ${pts.join(" ")} ${width},${height}`} fill={`url(#${id})`} />
      <polyline points={pts.join(" ")} fill="none" stroke={color} strokeWidth="1.6" strokeLinejoin="round" />
    </svg>
  );
}

export function ScoreRing({ score }) {
  const r = 20, c = 2 * Math.PI * r, v = Math.max(0, Math.min(100, score || 0));
  const color = v >= 70 ? "var(--green)" : v >= 50 ? "var(--amber)" : "var(--red)";
  return (
    <div className="ring" title="Quality score (0-100)">
      <svg width="48" height="48">
        <circle cx="24" cy="24" r={r} stroke="var(--panel-2)" strokeWidth="5" fill="none" />
        <circle cx="24" cy="24" r={r} stroke={color} strokeWidth="5" fill="none" strokeLinecap="round"
          strokeDasharray={`${(v / 100) * c} ${c}`} />
      </svg>
      <b style={{ color }}>{v}</b>
    </div>
  );
}

const TONE_ICON = {
  good: <CheckCircle2 size={15} color="var(--green)" />,
  warn: <AlertTriangle size={15} color="var(--amber)" />,
  info: <Info size={15} color="var(--blue)" />,
};

export function SetupCard({ s }) {
  const [zoom, setZoom] = useState(false);
  const st = STATUS[s.status] || STATUS.pending;
  const risk = s.entry - s.stop, reward = s.target - s.entry;
  return (
    <article className="panel setup">
      <div className="setup-head">
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="sym">{s.symbol}</span>
            <span className="tf">{s.timeframe}m</span>
            <Pill tone={st.tone}>{st.label}</Pill>
          </div>
          <div className="chips" style={{ marginTop: 8 }}>
            {(s.contexts || [s.kind]).map((c) => (
              <Pill key={c} tone={CONTEXT[c]?.tone || "gray"}>{CONTEXT[c]?.label || c}</Pill>
            ))}
            {s.change_pct != null && <Pill tone="green">{pct(s.change_pct, 0)} today</Pill>}
          </div>
        </div>
        <ScoreRing score={s.score} />
      </div>

      <div className="setup-chart">
        <LiveChart symbol={s.symbol} tf={s.timeframe} setups={[s]} height={320} showLegend={false}
          focusTime={s.inside_wall ?? wall(s.inside_time)} refreshMs={["pending", "triggered"].includes(s.status) ? 5000 : 30000} />
        {s.chart && <button className="snap-btn" onClick={() => setZoom(true)}>Alert snapshot</button>}
      </div>
      {zoom && (
        <div className="lightbox" onClick={() => setZoom(false)}>
          <img src={`/charts/${s.chart}`} alt="" />
        </div>
      )}

      <div className="levels">
        <div><small>Entry</small><b>{px(s.entry)}</b></div>
        <div><small>Stop</small><b className="down">{px(s.stop)}</b><em className="down">-{s.risk_pct.toFixed(1)}%</em></div>
        <div><small>Target (2R)</small><b className="up">{px(s.target)}</b><em className="up">+{s.target_pct.toFixed(1)}%</em></div>
      </div>
      <div className="rr">
        <div className="rr-bar">
          <div style={{ width: `${(risk / (risk + reward)) * 100}%`, background: "var(--red)", opacity: 0.85 }} />
          <div style={{ width: 2, background: "var(--bg)" }} />
          <div style={{ flex: 1, background: "var(--green)", opacity: 0.85 }} />
        </div>
        <div className="rr-legend"><span>risk 1R</span><span>reward {(reward / risk).toFixed(1)}R</span></div>
      </div>

      <ul className="reasons">
        {(s.reasons || []).map((r, i) => <li key={i}>{TONE_ICON[r.tone]}<span>{r.text}</span></li>)}
      </ul>

      <div className="timeline">
        <span>Inside bar <b>{tzTime(s.inside_time)}</b></span>
        {s.bars_ago != null && s.status === "pending" && <span>formed <b>{s.bars_ago}</b> bars ago</span>}
        {s.trigger_time && <span>Breakout <b>{tzTime(s.trigger_time)}</b></span>}
        {s.exit_time && <span>Closed <b>{tzTime(s.exit_time)}</b></span>}
        <span style={{ marginLeft: "auto" }} className="faint">NY time</span>
      </div>
    </article>
  );
}

const EVENT_ICON = {
  new: Zap, triggered: ArrowUpRight, target: Target, stopped: XCircle,
  cancelled: Ban, expired: Clock, runner: Rocket,
};

export function Feed({ events, now, limit }) {
  const list = limit ? events.slice(0, limit) : events;
  if (!list.length) return <Empty icon={Send}>No alerts yet today. They appear here the moment they go to Telegram.</Empty>;
  return (
    <div className="feed">
      {list.map((e, i) => {
        const ev = EVENT[e.event] || { label: e.event, tone: "gray" };
        const Icon = EVENT_ICON[e.event] || Info;
        return (
          <div className="feed-item" key={i}>
            <div className={`feed-icon t-${ev.tone}`}><Icon size={17} /></div>
            <div>
              <div className="title">
                <span className="sym">{e.symbol}</span>
                {e.timeframe && <span className="tf">{e.timeframe}m</span>}
                <Pill tone={ev.tone}>{ev.label}</Pill>
                {e.telegram === false && <Pill tone="red">Telegram failed</Pill>}
              </div>
              <div className="meta">
                {e.event === "runner"
                  ? `${pct(e.change_pct, 0)} · price ${px(e.price)} · float rotation ${e.float_rotation ? `x${e.float_rotation.toFixed(0)}` : "—"}`
                  : `Entry ${px(e.entry)} · Stop ${px(e.stop)} · Target ${px(e.target)} · Score ${e.score}`}
              </div>
            </div>
            <div className="time">{tzTime(e.time)}<br /><span>{ago(e.time, now)}</span></div>
          </div>
        );
      })}
    </div>
  );
}

