import React from 'react';

function IntegrationsPanel({ integrations }) {
  return (
    <div className="panel" style={{ flex: 1 }}>
      <div className="panel-title">INTEGRAÇÕES</div>
      <div className="integrations-grid">
        {integrations.map(item => {
          const color = item.configured ? '#8fc48a' : '#e0793c';
          return (
            <div className="row panel-row-item integration-row" key={item.name}>
              <span className="integration-dot" style={{ background: color }} />
              <div>
                <div className="integration-name">{item.label}</div>
                <div className="mono integration-status" style={{ color }}>{item.configured ? 'CONECTADO' : 'PENDENTE'}</div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default IntegrationsPanel;
