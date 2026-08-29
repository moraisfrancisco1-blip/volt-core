import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function App() {
  const [status, setStatus] = useState(null);
  const [systems, setSystems] = useState([]);
  const [events, setEvents] = useState([]);

  useEffect(() => {
    const load = async () => {
      try {
        const [statusData, systemsData, eventsData] = await Promise.all([
          fetch(`${API}/api/v1/status`).then(r => r.json()),
          fetch(`${API}/api/v1/systems`).then(r => r.json()),
          fetch(`${API}/api/v1/watch/events`).then(r => r.json()),
        ]);
        setStatus(statusData);
        setSystems(systemsData);
        setEvents(eventsData);
      } catch {
        setStatus({ core: 'offline' });
      }
    };
    load();
    const timer = setInterval(load, 10000);
    return () => clearInterval(timer);
  }, []);

  const critical = events.filter(event => event.priority === 'P1' || event.priority === 'P2');
  const modules = [
    ['CORE', status?.core?.toUpperCase() || 'CHECKING', 'Orchestrator'],
    ['WATCH', status ? 'ONLINE' : 'CHECKING', `${events.length} events received`],
    ['CONNECT', 'READY', `${systems.length} systems connected`],
    ['VOICE', 'PLANNED', `${critical.length} escalations waiting`],
  ];

  return (
    <main className="app-shell">
      <header className="topbar">
        <div><p className="eyebrow">AI OPERATIONS CENTER</p><h1>VOLT CORE</h1></div>
        <div className="system-status">{status?.core === 'online' ? 'SYSTEM ONLINE' : 'SYSTEM CHECK'}</div>
      </header>
      <section className="core-card">
        <div className="core-orb">VOLT</div>
        <div><p className="eyebrow">CENTRAL INTELLIGENCE</p><h2>Observe. Analyse. Coordinate.</h2><p>Mode: {status?.mode || 'starting'}. Production writes: {status?.production_write ? 'enabled' : 'disabled'}.</p></div>
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
