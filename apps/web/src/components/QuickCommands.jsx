import React, { useState } from 'react';

const ICONS = {
  search: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" /></svg>,
  refresh: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M21 12a9 9 0 1 1-2.6-6.4" /><path d="M21 3v6h-6" /></svg>,
  phone: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6 19.8 19.8 0 0 1-3.1-8.7A2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 2 .7 3a2 2 0 0 1-.4 2.1L8 10.3a16 16 0 0 0 6 6l1.5-1.4a2 2 0 0 1 2.1-.4c1 .3 2 .5 3 .7a2 2 0 0 1 1.4 2.1z" /></svg>,
  github: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M9 19c-4.3 1.4-4.3-2.5-6-3m12 5v-3.5c0-1 .1-1.4-.5-2 2-.2 4.5-1 4.5-4.5a3.6 3.6 0 0 0-1-2.5 3.3 3.3 0 0 0-.1-2.5s-.8-.3-2.9 1a10 10 0 0 0-5 0c-2-1.3-2.9-1-2.9-1a3.3 3.3 0 0 0-.1 2.5 3.6 3.6 0 0 0-1 2.5c0 3.5 2.5 4.3 4.5 4.5-.3.3-.5.9-.5 1.8v3.2" /></svg>,
};

function QuickCommands({ apiBase, systems, onInvestigationTriggered }) {
  const [sweepState, setSweepState] = useState('idle'); // idle | running | done | error
  const [callState, setCallState] = useState('idle'); // idle | calling | done | error
  const [showPicker, setShowPicker] = useState(false);
  const [systemChoice, setSystemChoice] = useState('');
  const [customSystem, setCustomSystem] = useState('');
  const [investigationState, setInvestigationState] = useState('idle'); // idle | sending | done | error

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

  const testCall = async () => {
    if (!window.confirm('Isto vai disparar uma chamada de voz real de teste. Confirmas?')) return;
    setCallState('calling');
    try {
      const response = await fetch(`${apiBase}/api/voice/test-call`, { method: 'POST' });
      setCallState(response.ok ? 'done' : 'error');
    } catch {
      setCallState('error');
    }
    setTimeout(() => setCallState('idle'), 4000);
  };

  const submitInvestigation = async () => {
    const systemId = (systemChoice === '__custom__' ? customSystem : systemChoice).trim();
    if (!systemId) return;
    setInvestigationState('sending');
    try {
      const response = await fetch(`${apiBase}/api/investigations/trigger-manual`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ system_id: systemId }),
      });
      if (response.ok) {
        setInvestigationState('done');
        onInvestigationTriggered?.();
        setTimeout(() => { setShowPicker(false); setInvestigationState('idle'); setSystemChoice(''); setCustomSystem(''); }, 1500);
        return;
      }
      setInvestigationState('error');
    } catch {
      setInvestigationState('error');
    }
    setTimeout(() => setInvestigationState('idle'), 3000);
  };

  const sweepLabel = sweepState === 'running' ? 'A VARRER…' : sweepState === 'done' ? 'VARREDURA DISPARADA' : sweepState === 'error' ? 'NÃO CONFIGURADO' : 'Forçar Varredura';
  const callLabel = callState === 'calling' ? 'A CHAMAR…' : callState === 'done' ? 'CHAMADA DISPARADA' : callState === 'error' ? 'FALHOU' : 'Testar Chamada';

  return (
    <div className="panel commands-panel">
      <div className="panel-title">COMANDOS RÁPIDOS</div>
      <div className="command-list">
        <button
          type="button"
          className="row panel-row-item command-row actionable command-row-button"
          onClick={() => setShowPicker(s => !s)}
        >
          <span style={{ color: '#f0b429' }}>{ICONS.search}</span>
          <span className="command-label">Nova Investigação</span>
        </button>

        {showPicker && (
          <div className="panel-row-item" style={{ padding: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
            <select className="picker-input" value={systemChoice} onChange={e => setSystemChoice(e.target.value)}>
              <option value="">Escolher sistema…</option>
              {(systems || []).map(s => <option value={s.name} key={s.name}>{s.name}</option>)}
              <option value="__custom__">Outro sistema…</option>
            </select>
            {systemChoice === '__custom__' && (
              <input className="picker-input" placeholder="nome-do-sistema" value={customSystem} onChange={e => setCustomSystem(e.target.value)} />
            )}
            <button
              type="button"
              className="row panel-row-item command-row actionable command-row-button"
              style={{ opacity: investigationState === 'sending' ? 0.7 : 1 }}
              onClick={submitInvestigation}
              disabled={investigationState === 'sending'}
            >
              <span className="command-label">
                {investigationState === 'sending' ? 'A DISPARAR…' : investigationState === 'done' ? 'INVESTIGAÇÃO PEDIDA' : investigationState === 'error' ? 'FALHOU' : 'Disparar'}
              </span>
            </button>
          </div>
        )}

        <button
          className="row panel-row-item command-row actionable command-row-button"
          style={{ opacity: sweepState === 'running' ? 0.7 : 1 }}
          onClick={forceSweep}
          disabled={sweepState === 'running'}
        >
          <span style={{ color: '#f0b429' }}>{ICONS.refresh}</span>
          <span className="command-label">{sweepLabel}</span>
        </button>

        <button
          className="row panel-row-item command-row actionable command-row-button"
          style={{ opacity: callState === 'calling' ? 0.7 : 1 }}
          onClick={testCall}
          disabled={callState === 'calling'}
        >
          <span style={{ color: '#f0b429' }}>{ICONS.phone}</span>
          <span className="command-label">{callLabel}</span>
        </button>

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
