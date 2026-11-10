import { useEffect, useRef, useState } from "react";
import { CandlestickChart, Lock } from "lucide-react";

const LEN = 6;

/** Full-screen PIN pad. The server checks the PIN; the browser only keeps an HttpOnly session cookie. */
export default function PinScreen({ configured, onSuccess }) {
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const input = useRef(null);

  useEffect(() => { input.current?.focus(); }, []);

  const submit = async (value) => {
    if (busy || value.length < LEN) return;
    setBusy(true);
    setError("");
    try {
      const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pin: value }) });
      const j = await r.json().catch(() => ({}));
      if (r.ok && j.ok) return onSuccess();
      setError(j.error || "Wrong PIN");
      setPin("");
    } catch {
      setError("Can't reach the server");
    } finally {
      setBusy(false);
      input.current?.focus();
    }
  };

  const press = (d) => {
    const v = (pin + d).slice(0, 12);
    setPin(v);
    if (v.length >= LEN && v.length === LEN) submit(v);
  };

  return (
    <div className="pin-wrap">
      <form className="pin-card panel" onSubmit={(e) => { e.preventDefault(); submit(pin); }}>
        <div className="brand-logo pin-logo"><CandlestickChart size={22} /></div>
        <h2>Inside Bar Bot</h2>
        <p className="muted">{configured ? "Enter your PIN to open the dashboard" : "No PIN is set on the server yet. Run set_pin.py on the host."}</p>
        <input ref={input} className="pin-hidden" inputMode="numeric" autoComplete="one-time-code" value={pin}
          onChange={(e) => { const v = e.target.value.replace(/\D/g, "").slice(0, 12); setPin(v); if (v.length === LEN) submit(v); }}
          disabled={!configured || busy} aria-label="PIN" />
        <div className="pin-dots" onClick={() => input.current?.focus()}>
          {Array.from({ length: Math.max(LEN, pin.length) }, (_, i) => <span key={i} className={i < pin.length ? "on" : ""} />)}
        </div>
        <div className={`pin-error${error ? " show" : ""}`}><Lock size={13} /> {error || " "}</div>
        <div className="pin-pad">
          {["1", "2", "3", "4", "5", "6", "7", "8", "9"].map((d) => (
            <button type="button" key={d} disabled={!configured || busy} onClick={() => press(d)}>{d}</button>
          ))}
          <button type="button" className="ghost" disabled={!configured || busy} onClick={() => setPin(pin.slice(0, -1))}>⌫</button>
          <button type="button" disabled={!configured || busy} onClick={() => press("0")}>0</button>
          <button type="submit" className="go" disabled={!configured || busy || pin.length < LEN}>→</button>
        </div>
      </form>
    </div>
  );
}
