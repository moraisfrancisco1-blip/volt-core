import React, { useCallback, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

const API = (import.meta.env.VITE_API_URL || 'https://api-production-c073.up.railway.app').replace(/\/$/, '');

function App() {
  const [dashboard, setDashboard] = useState(null);
  const [events, setEvents] = useState([]);
  const [escalations, setEscalations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      setError('');
      const [dashboardResponse, eventsResponse, escalationsResponse] = await Promise.all([
        fetch(`${API}/api/v1/dashboard`, { cache: 'no-store' }),
        fetch(`${API}/api/events?limit=50`, { cache: 'no-store' }),
        fetch(`${API}/api/escalations?limit=50`, { cache: 'no-store' }),
      ]);
      if (!dashboardResponse.ok) throw new Error(`dashboard unavailable (${dashboardResponse.status})`);
      if (!eventsResponse.ok) throw new Error(`event history unavailable (${eventsResponse.status})`);
      if (!escalationsResponse.ok) throw new Error(`escalation queue unavailable (${escalationsResponse.status})`);
      setDashboard(await dashboardResponse.json());
      setEvents(await eventsResponse.json());
      setEscalations(await escalationsResponse.json());
    } catch (err) {
      setError(err?.message || 'dashboard unavailable');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, [load]);

  const systems = dashboard?.systems || [];
  const monitorTargets = dashboard?.monitoring?.targets || [];
  const activeEscalations = escalations.filter(item => !['completed', 'cancelled'].includes(item.status));
  const activeCritical = activeEscalations.filter(item => ['P1', 'P2'].includes(item.priority));
  const activeCalls = activeEscalations.filter(item => item.action === 'call');
  const modules = [
    ['CORE', dashboard?.core?.toUpperCase() || (loading ? 'CHECKING' : 'OFFLINE'), 'Orchestrator'],
    ['WATCH', dashboard ? 'ONLINE' : (loading ? 'CHECKING' : 'OFFLINE'), `${events.length} events received`],
    ['CONNECT', dashboard ? 'READY' : (loading ? 'CHECKING' : 'OFFLINE'), `${systems.length} systems connected`],
    ['VOICE', activeCalls.length ? 'READY' : 'STANDBY', activeCalls.length ? `${activeCalls.length} P1 call${activeCalls.length === 1 ? '' : 's'} queued` : `${activeEscalations.length} escalations tracked`],
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
        <h2>{activeCritical.length} critical items</h2>
        <p>{activeEscalations.length} active escalations · P1 = phone call · P2 = approval required · P3 = notification · P4 = digest</p>
      </section>
      <section className="activity-card">
        <p className="eyebrow">MONITORING RUNTIME</p>
        <p>{dashboard?.monitoring?.started ? 'Monitor active' : 'Monitor not started'} · {dashboard?.monitoring?.target_count ?? 0} target(s) · every {dashboard?.monitoring?.interval_seconds ?? '—'} seconds</p>
        {monitorTargets.length === 0 ? <div className="empty-state">Waiting for a configured monitoring target.</div> : monitorTargets.map(target => <div className="event-row" key={target.system_id}><strong>{target.last_ok === true ? 'ONLINE' : target.last_ok === false ? 'CHECK FAILED' : 'CHECKING'}</strong> · {target.system_name} · last check {target.last_checked_at ? new Date(target.last_checked_at).toLocaleString() : 'pending'} · failures {target.consecutive_failures} · {target.last_detail || 'no result yet'}</div>)}
      </section>
      <section className="activity-card">
        <p className="eyebrow">MONITORED SYSTEMS</p>
        {systems.length === 0 ? <div className="empty-state">Waiting for the first monitored system.</div> : systems.map(system => <div className="event-row" key={system.name}><strong>{system.status || 'unknown'}</strong> · {system.name} · {system.environment || 'production'} · last signal {system.updated_at ? new Date(system.updated_at).toLocaleString() : 'not available'}</div>)}
      </section>
      <section className="activity-card">
        <p className="eyebrow">LIVE ACTIVITY</p>
        {loading ? <div className="empty-state">Loading live data...</div> : error && !dashboard ? <div className="empty-state">Unable to load live data. Retrying automatically...</div> : events.length === 0 ? <div className="empty-state">Waiting for the first event.</div> : events.map(event => <div className="event-row" key={event.id}><strong>{(event.severity || event.priority || 'EVENT').toUpperCase()} {event.priority ? `· ${event.priority}` : ''}</strong> · {event.system_name || event.system_id || 'unknown system'} · {event.title || event.message} · {event.status || 'active'} · {event.recommended_action || 'review'}</div>)}
      </section>
    </main>
  );
}

createRoot(document.getElementById('root')).render(<App />);
