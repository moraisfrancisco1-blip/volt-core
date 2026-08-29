import React, { useCallback, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

const API = (import.meta.env.VITE_API_URL || 'https://api-production-c073.up.railway.app').replace(/\/$/, '');

function App() {
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      setError('');
      const response = await fetch(`${API}/api/v1/dashboard`, { cache: 'no-store' });
      if (!response.ok) throw new Error(`dashboard unavailable (${response.status})`);
      setDashboard(await response.json());
    } catch (err) {
      setError(err?.message || 'dashboard unavailable');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, 10000);
    return () => clearInterval(timer);
  }, [load]);

  const systems = dashboard?.systems || [];
  const events = dashboard?.events || [];
  const criticalCount = Number.isFinite(dashboard?.critical_count)
    ? dashboard.critical_count
    : events.filter(event => event.priority === 'P1' || event.priority === 'P2').length;

  const modules = [
    ['CORE', dashboard?.core?.toUpperCase() || (loading ? 'CHECKING' : 'OFFLINE'), 'Orchestrator'],
    ['WATCH', dashboard ? 'ONLINE' : (loading ? 'CHECKING' : 'OFFLINE'), `${events.length} events received`],
    ['CONNECT', dashboard ? 'READY' : (loading ? 'CHECKING' : 'OFFLINE'), `${systems.length} systems connected`],
    ['VOICE', 'PLANNED', `${criticalCount} escalations waiting`],
  ];

  return (
    <main className="app-shell">
      <header className="topbar">
        <div><p className="eyebrow">AI OPERATIONS CENTER</p><h1>VOLT CORE</h1></div>
        <div className="system-status">{dashboard?.core === 'online' ? 'SYSTEM ONLINE' : loading ? 'SYSTEM CHECK' : 'SYSTEM OFFLINE'}</div>
      </header>
      <section className="core-card">
        <div className="core-orb">VOLT</div>
        <div><p className="eyebrow">CENTRAL INTELLIGENCE</p><h2>Observe. Analyse. Coordinate.</h2><p>Mode: {dashboard?.mode || (loading ? 'starting' : 'unavailable')}. Production writes: {dashboard?.production_write ? 'enabled' : 'disabled'}.</p></div>
      </section>
      <section className="module-grid">
        {modules.map(([name, moduleStatus, description]) => <article className="module-card" key={name}><div className="module-header"><h3>VOLT {name}</h3><span className="status">{moduleStatus}</span></div><p>{description}</p></article>)}
      </section>
      <section className="priority-card">
        <p className="eyebrow">ESCALATION QUEUE</p>
        <h2>{criticalCount} critical items</h2>
        <p>P1 = phone call · P2 = approval required · P3 = notification · P4 = digest</p>
      </section>
      <section className="activity-card">
        <p className="eyebrow">LIVE ACTIVITY</p>
        {loading ? <div className="empty-state">Loading live data...</div> : error && !dashboard ? <div className="empty-state">Unable to load live data. Retrying automatically...</div> : events.length === 0 ? <div className="empty-state">Waiting for the first event.</div> : events.map(event => <div className="event-row" key={event.id}><strong>{event.level || event.priority || 'EVENT'} {event.priority ? `· ${event.priority}` : ''}</strong> · {event.system || 'unknown system'} · {event.message || 'No message'} · {event.recommended_action || 'review'}</div>)}
      </section>
    </main>
  );
}

createRoot(document.getElementById('root')).render(<App />);