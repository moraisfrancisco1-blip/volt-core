import React from 'react';

const SOURCE_LABEL = {
  stripe_sandbox: 'DADOS SANDBOX -- NÃO É RECEITA REAL',
  no_source_configured: 'SEM DADOS FINANCEIROS AINDA',
  stripe_unavailable: 'STRIPE INDISPONÍVEL',
};
const SOURCE_COLOR = {
  stripe_sandbox: '#f0b429',
  no_source_configured: '#7d7062',
  stripe_unavailable: '#d9614f',
};

function ReconciliationRow({ record, onSelect }) {
  return (
    <div
      className={`feed-item${onSelect ? ' clickable-row' : ''}`}
      style={{ borderLeftColor: '#d9614f' }}
      onClick={onSelect ? () => onSelect(record) : undefined}
    >
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <span className="mono feed-item-tag" style={{ color: '#d9614f' }}>Deal #{record.deal_id}</span>
        <span className="mono feed-item-time">{SOURCE_LABEL[record.data_source] || record.data_source}</span>
      </div>
      <div className="feed-item-text">{record.note}</div>
    </div>
  );
}

function BackOfficePanel({ report, reconciliations, onSelectReconciliation }) {
  const unmatched = (reconciliations || []).filter(r => !r.match_found).slice(0, 6);
  const sourceColor = report ? (SOURCE_COLOR[report.data_source] || '#7d7062') : '#7d7062';

  return (
    <div className="panel">
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
        <div className="panel-title" style={{ margin: 0 }}>BACK OFFICE</div>
        {report && <span className="mono feed-item-time" style={{ color: sourceColor }}>{SOURCE_LABEL[report.data_source] || report.data_source}</span>}
      </div>

      <div className="panel-row-item" style={{ padding: 12, marginBottom: 16 }}>
        <div className="mono panel-title" style={{ marginBottom: 6 }}>RELATÓRIO INTERNO</div>
        {report
          ? (
            <>
              <div className="feed-item-text" style={{ marginBottom: 6 }}>{report.summary}</div>
              <div className="row" style={{ gap: 16 }}>
                <span className="mono feed-item-time">Fechados: {report.deals_closed_count}</span>
                <span className="mono feed-item-time">Com fatura: {report.deals_matched_count}</span>
                <span className="mono feed-item-time">Sem correspondência: {report.deals_unmatched_count}</span>
              </div>
            </>
          )
          : <div className="empty-state">Sem relatório gerado ainda.</div>}
      </div>

      <div className="mono panel-title" style={{ marginBottom: 8 }}>
        DEALS SEM CORRESPONDÊNCIA FINANCEIRA {unmatched.length > 0 ? `(${unmatched.length})` : ''}
      </div>
      {unmatched.length === 0
        ? <div className="empty-state">Sem discrepâncias sinalizadas.</div>
        : (
          <div className="feed-list">
            {unmatched.map(record => <ReconciliationRow record={record} onSelect={onSelectReconciliation} key={record.id} />)}
          </div>
        )}
    </div>
  );
}

export default BackOfficePanel;
