import React from 'react';

function SettingsView({ integrations }) {
  return (
    <div className="view-row">
      <div className="panel view-panel">
        <div className="panel-title">DEFINIÇÕES</div>
        <div className="empty-state" style={{ marginBottom: 12 }}>
          Sem gestão de definições disponível ainda -- as variáveis de ambiente e chaves
          continuam a configurar-se diretamente no Railway. Esta vista mostra, só para
          leitura, o estado das integrações já conhecidas.
        </div>
        <div className="integrations-grid">
          {(integrations || []).map(item => (
            <div className="row panel-row-item integration-row" key={item.name}>
              <span className="integration-dot" style={{ background: item.configured ? '#8fc48a' : '#e0793c' }} />
              <div>
                <div className="integration-name">{item.label}</div>
                <div className="mono integration-status" style={{ color: item.configured ? '#8fc48a' : '#e0793c' }}>{item.configured ? 'CONECTADO' : 'PENDENTE'}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default SettingsView;
