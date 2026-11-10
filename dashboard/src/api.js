import { useEffect, useRef, useState } from "react";

/** Poll a JSON endpoint every `ms` milliseconds. */
export function usePoll(url, ms = 5000) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const timer = useRef();

  useEffect(() => {
    if (!url) return undefined;
    let alive = true;
    const load = async () => {
      try {
        const r = await fetch(url, { cache: "no-store" });
        if (r.status === 401) { window.location.reload(); return; }  // session expired -> PIN screen
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        const j = await r.json();
        if (alive) { setData(j); setError(null); }
      } catch (e) {
        if (alive) setError(e.message || String(e));
      }
      if (alive && ms) timer.current = setTimeout(load, ms);
    };
    load();
    return () => { alive = false; clearTimeout(timer.current); };
  }, [url, ms]);

  return { data, error };
}

/** Re-render every second (clocks, countdowns). */
export function useNow(ms = 1000) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

export const px = (p) => (p == null ? "—" : p < 1 ? p.toFixed(4) : p.toFixed(2));
export const pct = (p, d = 1) => (p == null ? "—" : `${p >= 0 ? "+" : ""}${p.toFixed(d)}%`);
export const big = (n) => {
  if (n == null || Number.isNaN(n)) return "—";
  const a = Math.abs(n);
  if (a >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${(n / 1e3).toFixed(0)}K`;
  return n.toFixed(0);
};

export const tzTime = (iso, tz = "America/New_York", opts = {}) =>
  iso ? new Date(iso).toLocaleTimeString("en-GB", { timeZone: tz, hour: "2-digit", minute: "2-digit", ...opts }) : "—";

export const ago = (iso, now = new Date()) => {
  if (!iso) return "—";
  const s = Math.max(0, Math.round((now - new Date(iso)) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m ago`;
};

export const STATUS = {
  pending: { label: "Waiting for breakout", tone: "amber" },
  triggered: { label: "Triggered", tone: "green" },
  target: { label: "Target hit", tone: "blue" },
  stopped: { label: "Stopped out", tone: "red" },
  cancelled: { label: "Cancelled", tone: "gray" },
  expired: { label: "Expired", tone: "gray" },
  invalidated: { label: "No longer valid", tone: "gray" },
};

export const CONTEXT = {
  continuation: { label: "Uptrend continuation", tone: "green" },
  trendline_break: { label: "Downtrend line break", tone: "violet" },
  level_break: { label: "Value-zone breakout", tone: "orange" },
};

export const EVENT = {
  new: { label: "New setup", tone: "amber" },
  triggered: { label: "Breakout", tone: "green" },
  target: { label: "Target hit", tone: "blue" },
  stopped: { label: "Stopped out", tone: "red" },
  cancelled: { label: "Cancelled", tone: "gray" },
  expired: { label: "Expired", tone: "gray" },
  runner: { label: "Runner heads-up", tone: "violet" },
};
