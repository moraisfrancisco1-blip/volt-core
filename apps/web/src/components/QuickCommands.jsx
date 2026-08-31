import React, { useState } from 'react';

const ICONS = {
  search: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" /></svg>,
  refresh: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M21 12a9 9 0 1 1-2.6-6.4" /><path d="M21 3v6h-6" /></svg>,
  phone: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6 19.8 19.8 0 0 1-3.1-8.7A2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 2 .7 3a2 2 0 0 1-.4 2.1L8 10.3a16 16 0 0 0 6 6l1.5-1.4a2 2 0 0 1 2.1-.4c1 .3 2 .5 3 .7a2 2 0 0 1 1.4 2.1z" /></svg>,
  github: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M9 19c-4.3 1.4-4.3-2.5-6-3m12 5v-3.5c0-1 .1-1.4-.5-2 2-.2 4.5-1 4.5-4.5a3.6 3.6 0 0 0-1-2.5 3.3 3.3 0 0 0-.1-2.5s-.8-.3-2.9 1a10 10 0 0 0-5 0c-2-1.3-2.9-1-2.9-1a3.3 3.3 0 0 0-.1 2.5 3.6 3.6 0 0 0-1 2.5c0 3.5 2.5 4.3 4.5 4.5-.3.3-.5.9-.5 1.8v3.2" /></svg>,
};

function QuickCommands({ apiBase }) {
  const [sweepState, setSweepState] = useState('idle'); // idle | running | done | error

  const forceSweep = async () => {
    setSweepState('running');
    try {
      const response = await fetch(`${apiBase}/api/monitoring-sweeps/run`, { method: 'POST' });
      const payload = await response.json();
      setSweepState(payload.triggered ? 'done' : 'error');
    } catch {
      setSweepState('error');
    }
    setTimeout(() => setSweepState('idle'), 3000);
  };

  const sweepLabel = sweepState === 'running' ? 'A VARRER…' : sweepState === 'done' ? 'VARREDURA DISPARADA' : sweepState === 'error' ? 'NÃO CONFIGURADO' : 'Forçar Varredura';

  return (
    <div className="panel commands-panel">
      <div className="panel-title">COMANDOS RÁPIDOS</div>
      <div className="command-list">
        <div className="row panel-row-item command-row inactive">
          <span style={{ color: '#f0b429' }}>{ICONS.search}</span>
          <span className="command-label">Nova Investigação</span>
        </div>

        <button
          className="row panel-row-item command-row actionable command-row-button"
          style={{ opacity: sweepState === 'running' ? 0.7 : 1 }}
          onClick={forceSweep}
          disabled={sweepState === 'running'}
        >
          <span style={{ color: '#f0b429' }}>{ICONS.refresh}</span>
          <span className="command-label">{sweepLabel}</span>
        </button>

        <div className="row panel-row-item command-row inactive">
          <span style={{ color: '#f0b429' }}>{ICONS.phone}</span>
          <span className="command-label">Testar Chamada</span>
        </div>

        <a
          className="row panel-row-item command-row actionable"
          href="https://github.com/moraisfrancisco1-blip/volt-core"
          target="_blank"
          rel="noreferrer"
        >
          <span style={{ color: '#f0b429' }}>{ICONS.github}</span>
          <span className="command-label">Ver GitHub</span>
        </a>
      </div>
    </div>
  );
}

export default QuickCommands;
