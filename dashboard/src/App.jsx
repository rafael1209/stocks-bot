import { useEffect, useState } from "react";
import {
  AlertOctagon, BarChart3, Bell, BookOpen, CandlestickChart, Crosshair, HeartPulse, LayoutDashboard, LineChart, Wallet, LogOut, Radar,
} from "lucide-react";
import { usePoll, useNow } from "./api";
import { Pill } from "./components/ui";
import PinScreen from "./components/PinScreen";
import { Alerts, Backtest, Calibration, Charts, Health, Overview, Pnl, Scanner, Setups, Strategy } from "./components/pages";

const PAGES = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "setups", label: "Setups", icon: Crosshair },
  { id: "charts", label: "Live charts", icon: LineChart },
  { id: "scanner", label: "Scanner", icon: Radar },
  { id: "pnl", label: "P&L", icon: Wallet },
  { id: "alerts", label: "Alerts", icon: Bell },
  { id: "strategy", label: "Strategy", icon: BookOpen },
  { id: "backtest", label: "Backtest", icon: BarChart3 },
  { id: "calibration", label: "My trades", icon: CandlestickChart },
  { id: "health", label: "System", icon: HeartPulse },
];

const SESSION = {
  premarket: { label: "Pre-market", tone: "violet" },
  regular: { label: "Market open", tone: "green" },
  "no-entry window": { label: "Open · no entries (first 15m)", tone: "amber" },
  "after-hours": { label: "After-hours", tone: "blue" },
  closed: { label: "Market closed", tone: "gray" },
};

const SUBTITLE = {
  overview: "Everything the bot sees right now",
  setups: "Inside-bar setups alerted today, followed to the end",
  charts: "Live candles with the bot's levels – TradingView engine",
  scanner: "Top gainers that passed every filter",
  pnl: "What every breakout would have made, traded exactly by the plan",
  alerts: "Every message sent to Telegram",
  strategy: "The rules the bot trades by – live from config.yaml",
  backtest: "How the rules did on recent minute data",
  calibration: "Your trades, to tune the bot to how you trade",
  health: "Process, data feed and errors",
};

function Clock({ label, tz, now }) {
  return (
    <div className="clock">
      <small>{label}</small>
      <b>{now.toLocaleTimeString("en-GB", { timeZone: tz, hour: "2-digit", minute: "2-digit", second: "2-digit" })}</b>
    </div>
  );
}

export default function App() {
  const [auth, setAuth] = useState(null);
  const check = () => fetch("/api/session", { cache: "no-store" }).then((r) => r.json())
    .then(setAuth).catch(() => setAuth({ authenticated: false, configured: true }));
  useEffect(() => { check(); }, []);
  if (!auth) return null;
  if (!auth.authenticated) return <PinScreen configured={auth.configured} onSuccess={check} />;
  return <Dashboard onLogout={() => fetch("/api/logout", { method: "POST" }).then(check)} />;
}

function Dashboard({ onLogout }) {
  const [page, setPage] = useState(() => {
    try { return localStorage.getItem("page") || "overview"; } catch { return "overview"; }
  });
  useEffect(() => { try { localStorage.setItem("page", page); } catch { /* private mode */ } }, [page]);

  const now = useNow();
  const { data: status, error } = usePoll("/api/status", 4000);
  const { data: events } = usePoll("/api/events?limit=400", 6000);
  const { data: config } = usePoll("/api/config", 30000);
  const { data: backtest } = usePoll(page === "backtest" ? "/api/backtest" : null, 0);
  const { data: pnl } = usePoll(page === "pnl" ? "/api/pnl" : null, 30000);
  const { data: trades } = usePoll(page === "calibration" ? "/api/trades" : null, 0);

  const ev = events || [];
  const active = (status?.setups || []).filter((s) => ["pending", "triggered"].includes(s.status)).length;
  const sess = SESSION[status?.session] || SESSION.closed;
  const next = status?.next_scan ? Math.max(0, Math.round((new Date(status.next_scan) - now) / 1000)) : null;
  const current = PAGES.find((p) => p.id === page);

  const nav = PAGES.map((p) => (
    <button key={p.id} className={`nav-item${page === p.id ? " active" : ""}`} onClick={() => setPage(p.id)}>
      <p.icon size={17} /> {p.label}
      {p.id === "setups" && active > 0 && <span className="count">{active}</span>}
    </button>
  ));

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-logo"><CandlestickChart size={19} /></div>
          <div><b>Inside Bar Bot</b><span>momentum scanner</span></div>
        </div>
        {nav}
        <div className="sidebar-foot">
          <div style={{ display: "flex", justifyContent: "space-between" }}><span>Bot</span>
            <b style={{ color: status?.alive ? "var(--green)" : "var(--red)" }}>{status?.alive ? "running" : "stopped"}</b></div>
          <div style={{ display: "flex", justifyContent: "space-between" }}><span>Next scan</span>
            <b className="mono">{status?.alive && next != null ? `${next}s` : "—"}</b></div>
          <div style={{ display: "flex", justifyContent: "space-between" }}><span>Data</span>
            <b>{status?.data_source === "yahoo" ? "Yahoo" : "TradingView"}</b></div>
          <button className="logout" onClick={onLogout}><LogOut size={14} /> Lock</button>
        </div>
      </aside>

      <main className="main">
        <nav className="mobile-nav">{nav}</nav>
        <div className="topbar">
          <div>
            <h1>{current.label}</h1>
            <div className="sub">{SUBTITLE[page]}</div>
          </div>
          <span className="spacer" />
          <div className="topbar-right">
            <Pill tone={status?.alive ? "green" : "red"} live={!!status?.alive}>
              {status?.alive ? `Live · scan #${status.scans}` : "Bot stopped"}
            </Pill>
            <Pill tone={sess.tone}>{sess.label}</Pill>
            <Clock label="New York" tz="America/New_York" now={now} />
            <Clock label="Israel" tz="Asia/Jerusalem" now={now} />
          </div>
        </div>

        {error && (
          <div className="banner err"><AlertOctagon size={18} />
            <span>Can't reach the dashboard server ({error}). Start it with <b className="mono">py dashboard_api.py</b>.</span></div>
        )}
        {status && !status.alive && !error && (
          <div className="banner warn"><AlertOctagon size={18} />
            <span>{status.message || `The bot hasn't updated for ${status.seconds_since_update}s – it may be stopped. Start it with `}
              {!status.message && <b className="mono">py main.py</b>}</span></div>
        )}

        {page === "overview" && <Overview status={status} events={ev} now={now} />}
        {page === "setups" && <Setups status={status} />}
        {page === "charts" && <Charts status={status} />}
        {page === "scanner" && <Scanner status={status} config={config} />}
        {page === "pnl" && <Pnl pnl={pnl} />}
        {page === "alerts" && <Alerts events={ev} now={now} />}
        {page === "strategy" && <Strategy config={config} />}
        {page === "backtest" && <Backtest backtest={backtest} />}
        {page === "calibration" && <Calibration trades={trades} />}
        {page === "health" && <Health status={status} now={now} />}
      </main>
    </div>
  );
}
