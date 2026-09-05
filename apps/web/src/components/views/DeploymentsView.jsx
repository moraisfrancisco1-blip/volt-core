import React from 'react';

function DeploymentsView() {
  return (
    <div className="view-row">
      <div className="panel view-panel">
        <div className="panel-title">IMPLEMENTAÇÕES</div>
        <div className="empty-state">
          Sem histórico de implementações disponível ainda -- não existe nenhuma integração
          com o histórico de deploys da Railway neste dashboard. Consulta o painel da
          Railway diretamente por agora.
        </div>
      </div>
    </div>
  );
}

export default DeploymentsView;
