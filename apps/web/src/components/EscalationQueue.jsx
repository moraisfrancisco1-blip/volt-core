import React from 'react';

const LEVEL_COLOR = { P1: '#d9614f', P2: '#e0793c', P3: '#f0b429', P4: '#8a9bd8' };

const STATE_MAP = {
  calling: { label: 'A CHAMAR', color: '#d9614f' },
  queued: { label: 'EM FILA', color: '#e0793c' },
  notified: { label: 'RECONHECIDO', color: '#e0793c' },
  acknowledged: { label: 'RECONHECIDO', color: '#e0793c' },
  completed: { label: 'RESOLVIDO', color: '#8fc48a' },
  cancelled: { label: 'CANCELADO', color: '#7d7062' },
};

function EscalationQueue({ escalations, limit = 8, onSelect }) {
  const items = limit ? escalations.slice(0, limit) : escalations;
  return (
    <div className="panel queue-panel">
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
        <div className="panel-title" style={{ margin: 0 }}>FILA DE ESCALONAMENTO</div>
        <span className="mono" style={{ fontSize: 9, color: '#8a7c68' }}>HOJE</span>
      </div>
      <div className="queue-list">
        {items.length === 0
          ? <div className="empty-state">Sem escalonamentos ativos.</div>
          : items.map(item => {
              const state = STATE_MAP[item.status] || { label: (item.status || '—').toUpperCase(), color: '#7d7062' };
              return (
                <div
                  className={`row queue-row${onSelect ? ' clickable-row' : ''}`}
                  key={item.id}
                  onClick={onSelect ? () => onSelect(item) : undefined}
                >
                  <div className="row" style={{ gap: 8 }}>
                    <span className="mono queue-level" style={{ color: LEVEL_COLOR[item.priority] || '#8a9bd8' }}>{item.priority}</span>
                    <span className="queue-text">{item.system} — {item.action}</span>
                  </div>
                  <span className="mono queue-state" style={{ color: state.color }}>{state.label}</span>
                </div>
              );
            })}
      </div>
    </div>
  );
}

export default EscalationQueue;
