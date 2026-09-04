import React from 'react';

function timeAgo(isoString) {
  if (!isoString) return '—';
  const diffMs = Date.now() - new Date(isoString).getTime();
  const hours = Math.floor(diffMs / 3600000);
  if (hours < 1) return 'agora';
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

const AREAS = [
  ['competitors_summary', 'CONCORRÊNCIA'],
  ['regulation_summary', 'REGULAÇÃO'],
  ['price_signals_summary', 'SINAIS DE PREÇO'],
  ['industry_news_summary', 'NOTÍCIAS DO SETOR'],
];

function MarketIntelligencePanel({ reports }) {
  const latest = reports?.[0];

  if (!latest) {
    return (
      <div className="panel">
        <div className="panel-title">INTELIGÊNCIA DE MERCADO</div>
        <div className="empty-state">Sem resumos semanais registados ainda.</div>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
        <div className="panel-title" style={{ margin: 0 }}>INTELIGÊNCIA DE MERCADO</div>
        <span className="mono feed-item-time">
          {latest.status === 'failed' ? 'falhou' : 'atualizado'} · {timeAgo(latest.completed_at || latest.created_at)}
        </span>
      </div>
      {latest.status === 'failed'
        ? <div className="empty-state">Última execução falhou: {latest.error || 'motivo desconhecido'}</div>
        : (
          <div className="market-intel-grid">
            {AREAS.map(([field, label]) => (
              <div className="panel-row-item" style={{ padding: 12 }} key={field}>
                <div className="mono panel-title" style={{ marginBottom: 6 }}>{label}</div>
                <div className="feed-item-text">{latest[field] || 'sem novidades esta semana'}</div>
              </div>
            ))}
          </div>
        )}
    </div>
  );
}

export default MarketIntelligencePanel;
