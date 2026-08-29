import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function App() {
  const [dashboard, setDashboard] = useState(null);

  useEffect(() => {
    const load = async () => {
      try {
        const response = await fetch(`${API}/api/v1/dashboard`);
        if (!response.ok) throw new Error('dashboard unavailable');
        setDashboard(await response.json());
      } catch {
        setDashboard(null);
      }
    };
    load();
    const timer = setInterval(load, 10000);
    return () => clearInterval(timer);
  }, []);

  const systems = dashboard?.systems || [];
  const events = dashboard?.events || [];
  const critical = events.filter(event => event.priority === 'P1' || event.priority === 'P2');
  const modules = [
    ['CORE', dashboard?.core?.toUpperCase() || 'CHECKING', 'Orchestrator'],
    ['WATCH', dashboard ? 'ONLINE' : 'CHECKING', `${events.length} events received`],
    ['CONNECT', dashboard ? 'READY' : 'CHECKING', `${systems.length} systems connected`],
    ['VOICE', 'PLANNED', `${critical.length} escalations waiting`],
  ];

  return (
    <main className="app-shell">
      <header className="topbar">
        <div><p className="eyebrow">AI OPERATIONS CENTER</p><h1>VOLT CORE</h1></div>
        <div className="system-status">{dashboard?.core === 'online' ? 'SYSTEM ONLINE' : 'SYSTEM CHECK'}</div>
      </header>
      <section className="core-card">
        <div className="core-orb">VOLT</div>
        <div><p className="eyebrow">CENTRAL INTELLIGENCE</p><h2>Observe. Analyse. Coordinate.</h2><p>Mode: {dashboard?.mode || 'starting'}. Production writes: {dashboard?.production_write ? 'enabled' : 'disabled'}.</p></div>
      </section>
      <section className="module-grid">
        {modules.map(([name, moduleStatus, description]) => <article className="module-card" key={name}><div className="module-header"><h3>VOLT {name}</h3><span className="status">{moduleStatus}</span></div><p>{description}</p></article>)}
      </section>
      <section className="priority-card">
        <p className="eyebrow">ESCALATION QUEUE</p>
        <h2>{critical.length} critical items</h2>
        <p>P1 = phone call · P2 = approval required · P3 = notification · P4 = digest</p>
      </section>
      <section className="activity-card">
        <p className="eyebrow">LIVE ACTIVITY</p>
        {events.length === 0 ? <div className="empty-state">Waiting for the first event.</div> : events.map(event => <div className="event-row" key={event.id}><strong>{event.priority || event.level}</strong> · {event.system} · {event.message} · {event.recommended_action || 'review'}</div>)}
      </section>
    </main>
  );
}

createRoot(document.getElementById('root')).render(<App />);