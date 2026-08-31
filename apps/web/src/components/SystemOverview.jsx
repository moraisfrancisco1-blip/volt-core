import React from 'react';

const ICONS = {
  orchestrator: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" /></svg>,
  memory: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M12 3a9 9 0 1 0 9 9" /><path d="M12 3v9l6 3" /></svg>,
  voice: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6 19.8 19.8 0 0 1-3.1-8.7A2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 2 .7 3a2 2 0 0 1-.4 2.1L8 10.3a16 16 0 0 0 6 6l1.5-1.4a2 2 0 0 1 2.1-.4c1 .3 2 .5 3 .7a2 2 0 0 1 1.4 2.1z" /></svg>,
  agents: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="9" cy="8" r="3.2" /><path d="M2.5 20a6.5 6.5 0 0 1 13 0" /><circle cx="18" cy="9" r="2.6" /><path d="M15.8 13a5 5 0 0 1 6.7 4.7" /></svg>,
  system: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M20 6 9 17l-5-5" /></svg>,
};

function SystemOverview({ investigationCount, twilioConfigured, agentsStatus, systemOk, iconColor }) {
  const activeAgents = agentsStatus.filter(a => a.state !== 'idle').length;
  const standbyAgents = agentsStatus.length - activeAgents;

  const items = [
    { label: 'Orquestrador', value: 'ATIVO', valueColor: '#8fc48a', icon: ICONS.orchestrator },
    { label: 'Memória (investigações)', value: `${investigationCount} guardadas`, valueColor: '#d8cdbc', icon: ICONS.memory },
    { label: 'Linha de Voz', value: twilioConfigured ? 'CONFIGURADA' : 'PENDENTE', valueColor: twilioConfigured ? '#8fc48a' : '#e0793c', icon: ICONS.voice },
    { label: 'Agentes', value: `${activeAgents} ativos · ${standbyAgents} standby`, valueColor: '#d8cdbc', icon: ICONS.agents },
    { label: 'Sistema', value: systemOk ? 'ÓTIMO' : 'ATENÇÃO', valueColor: systemOk ? '#8fc48a' : '#e0793c', icon: ICONS.system },
  ];

  return (
    <div className="panel overview-panel">
      <div className="panel-title">VOLT CORE · VISÃO GERAL</div>
      {items.map(item => (
        <div className="row overview-item" key={item.label}>
          <div className="row overview-label">
            <span style={{ color: iconColor }}>{item.icon}</span>
            <span>{item.label}</span>
          </div>
          <span className="mono overview-value" style={{ color: item.valueColor }}>{item.value}</span>
        </div>
      ))}
    </div>
  );
}

export default SystemOverview;
