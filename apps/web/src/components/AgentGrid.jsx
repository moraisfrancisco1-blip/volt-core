import React from 'react';

const STATE_COLOR = { working: '#f0b429', error: '#d9614f', idle: '#7d7062' };
const STATE_LABEL = { working: 'A TRABALHAR', error: 'ERRO', idle: 'IDLE' };

function AgentGrid({ agents }) {
  return (
    <div className="panel agents-panel">
      <div className="panel-title">AGENTES ATIVOS</div>
      <div className="agent-grid">
        {agents.map(agent => {
          const color = STATE_COLOR[agent.state] || STATE_COLOR.idle;
          return (
            <div className="panel-row-item agent-card" key={agent.id}>
              <div className="row" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
                <span className="agent-card-name">{agent.label}</span>
                <span className="agent-status-dot" style={{ background: color, boxShadow: `0 0 5px ${color}` }} />
              </div>
              <div className="mono agent-status-label" style={{ color }}>{STATE_LABEL[agent.state] || STATE_LABEL.idle}</div>
              <div className="agent-feed-line">{agent.lastActivityText || 'Sem histórico ainda.'}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default AgentGrid;
