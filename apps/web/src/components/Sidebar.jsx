import React, { useState } from 'react';

const NAV_ITEMS = [
  { label: 'Centro de Comando', viewId: 'dashboard', icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></svg> },
  { label: 'Volt Core', viewId: 'volt-core', icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="3" /></svg> },
  { label: 'Agentes', viewId: 'agents', icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="9" cy="8" r="3.2" /><path d="M2.5 20a6.5 6.5 0 0 1 13 0" /><circle cx="18" cy="9" r="2.6" /><path d="M15.8 13a5 5 0 0 1 6.7 4.7" /></svg> },
  { label: 'Escalonamentos', viewId: 'escalations', icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /><path d="M12 9v4" /><path d="M12 17h.01" /></svg> },
  { label: 'Registo de Eventos', viewId: 'events', icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M8 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2h-2" /><rect x="8" y="1.5" width="8" height="4" rx="1" /><path d="M8 12h8M8 16h8" /></svg> },
  { label: 'Integrações', viewId: 'integrations', icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M9 3v4M15 3v4M6 7h12l-1 5H7z" /><path d="M8 12v3a4 4 0 0 0 8 0v-3" /></svg> },
  { label: 'Implementações', viewId: 'deployments', icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M12 3v12" /><path d="M7 10l5 5 5-5" /><path d="M4 19h16" /></svg> },
  { label: 'Definições', viewId: 'settings', icon: <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6V21a2 2 0 1 1-4 0v-.2a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.6-1H3a2 2 0 1 1 0-4h.2a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.6V3a2 2 0 1 1 4 0v.2a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.6 1H21a2 2 0 1 1 0 4h-.2a1.7 1.7 0 0 0-1.5 1z" /></svg> },
];

const PHONE_ICON = <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#e0793c" strokeWidth="1.8"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6 19.8 19.8 0 0 1-3.1-8.7A2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 2 .7 3a2 2 0 0 1-.4 2.1L8 10.3a16 16 0 0 0 6 6l1.5-1.4a2 2 0 0 1 2.1-.4c1 .3 2 .5 3 .7a2 2 0 0 1 1.4 2.1z" /></svg>;

function Sidebar({ twilioConfigured, activeView, onNavigate, apiBase }) {
  const [callState, setCallState] = useState('idle'); // idle | calling | done | error

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

  const callLabel = callState === 'calling' ? 'A CHAMAR…' : callState === 'done' ? 'CHAMADA DISPARADA' : callState === 'error' ? 'FALHOU' : 'TESTAR CHAMADA';

  return (
    <div className="sidebar">
      <div className="nav-list">
        {NAV_ITEMS.map(item => (
          <button
            type="button"
            className={`nav-item${activeView === item.viewId ? ' active' : ''}`}
            key={item.viewId}
            onClick={() => onNavigate(item.viewId)}
          >
            <span style={{ color: activeView === item.viewId ? '#f0b429' : '#8a7c68', display: 'flex' }}>{item.icon}</span>
            <span className="display nav-item-label">{item.label}</span>
          </button>
        ))}
      </div>

      <div className="sidebar-spacer" />

      <div className="panel" style={{ padding: 14, marginTop: 12 }}>
        <div className="panel-title" style={{ marginBottom: 10 }}>LINHA DE ESCALONAMENTO</div>
        <div className="row" style={{ gap: 10, marginBottom: 10 }}>
          <div style={{ width: 36, height: 36, borderRadius: '50%', background: 'rgba(224,121,60,0.12)', border: '1px solid rgba(224,121,60,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            {PHONE_ICON}
          </div>
          <div>
            <div style={{ fontSize: 12, fontWeight: 600 }}>Twilio Voice</div>
            <div className="mono" style={{ fontSize: 10, color: twilioConfigured ? '#8fc48a' : '#e0793c' }}>
              {twilioConfigured ? 'CONFIGURADA' : 'CONFIGURAÇÃO PENDENTE'}
            </div>
          </div>
        </div>
        <div style={{ fontSize: 11, color: '#a89680', lineHeight: 1.5, marginBottom: 10 }}>
          {twilioConfigured ? 'Chamadas P1–P3 prontas a disparar.' : 'Chamadas P1–P3 ainda por ativar.'}
        </div>
        <button
          type="button"
          className="mono"
          style={{ width: '100%', textAlign: 'center', fontSize: 10.5, padding: 7, borderRadius: 6, border: '1px solid rgba(240,180,60,0.25)', background: 'none', color: '#f0b429', cursor: callState === 'calling' ? 'default' : 'pointer', opacity: callState === 'calling' ? 0.7 : 1 }}
          onClick={testCall}
          disabled={callState === 'calling'}
        >
          {callLabel}
        </button>
      </div>
    </div>
  );
}

export default Sidebar;
