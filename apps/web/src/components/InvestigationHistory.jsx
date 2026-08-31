import React from 'react';

function formatDuration(seconds) {
  if (seconds == null) return '—';
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function InvestigationHistory({ investigations, fetchLimit }) {
  const total = investigations.length;
  const completed = investigations.filter(i => i.status === 'completed');
  const failed = investigations.filter(i => i.status === 'failed');
  const decided = completed.length + failed.length;
  const resolvedPct = decided > 0 ? Math.round((completed.length / decided) * 100) : null;
  const durations = completed
    .filter(i => i.created_at && i.completed_at)
    .map(i => (new Date(i.completed_at).getTime() - new Date(i.created_at).getTime()) / 1000)
    .filter(s => s >= 0);
  const avgSeconds = durations.length > 0 ? durations.reduce((a, b) => a + b, 0) / durations.length : null;

  if (total === 0) {
    return (
      <div className="panel" style={{ flex: 1 }}>
        <div className="panel-title">HISTÓRICO DE INVESTIGAÇÕES</div>
        <div className="history-empty">Sem investigações registadas ainda.</div>
      </div>
    );
  }

  return (
    <div className="panel" style={{ flex: 1 }}>
      <div className="panel-title">HISTÓRICO DE INVESTIGAÇÕES</div>
      <div className="row history-stats">
        <div>
          <div className="mono history-stat-value" style={{ color: '#f0b429' }}>{total === fetchLimit ? `${total}+` : total}</div>
          <div className="mono history-stat-label">TOTAL</div>
        </div>
        <div>
          <div className="mono history-stat-value" style={{ color: '#f5ede0' }}>{formatDuration(avgSeconds)}</div>
          <div className="mono history-stat-label">TEMPO MÉDIO</div>
        </div>
        <div>
          <div className="mono history-stat-value" style={{ color: '#8fc48a' }}>{resolvedPct == null ? '—' : `${resolvedPct}%`}</div>
          <div className="mono history-stat-label">RESOLVIDAS</div>
        </div>
      </div>
    </div>
  );
}

export default InvestigationHistory;
