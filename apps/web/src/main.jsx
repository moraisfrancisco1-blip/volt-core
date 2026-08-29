import React from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

const modules = [
  ['CORE', 'ONLINE', 'Orchestrator'],
  ['WATCH', 'STANDBY', 'Production monitoring'],
  ['CONNECT', 'READY', 'System connectors'],
  ['VOICE', 'OFFLINE', 'Phone communication'],
];

function App() {
  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">AI OPERATIONS CENTER</p>
          <h1>VOLT CORE</h1>
        </div>
        <div className="system-status">SYSTEM ONLINE</div>
      </header>
      <section className="core-card">
        <div className="core-orb">VOLT</div>
        <div>
          <p className="eyebrow">CENTRAL INTELLIGENCE</p>
          <h2>Observe. Analyse. Coordinate.</h2>
          <p>Production mode is protected. Autonomous writes are disabled.</p>
        </div>
      </section>
      <section className="module-grid">
        {modules.map(([name, status, description]) => (
          <article className="module-card" key={name}>
            <div className="module-header">
              <h3>VOLT {name}</h3>
              <span className="status">{status}</span>
            </div>
            <p>{description}</p>
          </article>
        ))}
      </section>
      <section className="activity-card">
        <p className="eyebrow">ACTIVITY</p>
        <div className="empty-state">Waiting for the first connected system.</div>
      </section>
    </main>
  );
}

createRoot(document.getElementById('root')).render(<App />);
