import React, { useState } from 'react';

function DraftRow({ draft, apiBase, onUpdated }) {
  const [state, setState] = useState('idle'); // idle | sending | done | error

  const approveAndSend = async () => {
    setState('sending');
    try {
      const response = await fetch(`${apiBase}/api/customer-response-drafts/${draft.id}/approve-and-send`, { method: 'POST' });
      const payload = await response.json();
      onUpdated(payload);
      setState(payload.status === 'approved_sent' ? 'done' : 'error');
    } catch {
      setState('error');
    }
    setTimeout(() => setState('idle'), 4000);
  };

  const isPending = draft.status === 'pending_approval';
  const label = state === 'sending' ? 'A ENVIAR…' : state === 'done' ? 'ENVIADO' : state === 'error' ? 'FALHOU' : 'Aprovar e Enviar';

  return (
    <div className="panel-row-item" style={{ padding: 12, marginBottom: 8 }}>
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 6 }}>
        <span className="agent-card-name">{draft.subject}</span>
        <span className="mono feed-item-time">
          {draft.status === 'pending_approval' ? 'pendente de aprovação' : draft.status === 'approved_sent' ? 'enviado' : 'falhou'}
        </span>
      </div>
      <div className="feed-item-text" style={{ marginBottom: 8, whiteSpace: 'pre-wrap' }}>{draft.body}</div>
      {isPending && (
        <button
          type="button"
          className="row panel-row-item command-row actionable command-row-button"
          style={{ opacity: state === 'sending' ? 0.7 : 1 }}
          onClick={approveAndSend}
          disabled={state === 'sending'}
        >
          <span className="command-label">{label}</span>
        </button>
      )}
    </div>
  );
}

function EscalatedRow({ query, onSelect }) {
  return (
    <div
      className={`feed-item${onSelect ? ' clickable-row' : ''}`}
      style={{ borderLeftColor: '#d9614f' }}
      onClick={onSelect ? () => onSelect(query) : undefined}
    >
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <span className="mono feed-item-tag" style={{ color: '#d9614f' }}>{query.sensitive_reason || 'sinalizado'}</span>
        <span className="mono feed-item-time">{query.customer_name || query.customer_email || 'anónimo'}</span>
      </div>
      <div className="feed-item-text">{query.question}</div>
    </div>
  );
}

function CustomerPanel({ queries, drafts, patterns, apiBase, onDraftUpdated, onSelectQuery }) {
  const escalated = (queries || []).filter(q => q.status === 'sensitive_escalated').slice(0, 6);
  const pendingDrafts = (drafts || []).filter(d => d.status === 'pending_approval');
  const recentDrafts = (drafts || []).slice(0, 4);
  const flaggedPatterns = (patterns || []).filter(p => p.occurrence_count >= 2).slice(0, 4);
  const hasRealChannel = false; // no support channel is connected to VOLT CORE yet -- see note below

  return (
    <div className="panel">
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
        <div className="panel-title" style={{ margin: 0 }}>CUSTOMER</div>
        {!hasRealChannel && <span className="mono feed-item-time">sem canal de suporte real ligado ainda</span>}
      </div>

      <div className="row" style={{ gap: 16, alignItems: 'flex-start' }}>
        <div style={{ flex: 1 }}>
          <div className="mono panel-title" style={{ marginBottom: 8 }}>
            ATENÇÃO HUMANA {escalated.length > 0 ? `(${escalated.length})` : ''}
          </div>
          {escalated.length === 0
            ? <div className="empty-state">Sem pedidos sinalizados.</div>
            : <div className="feed-list">{escalated.map(q => <EscalatedRow query={q} onSelect={onSelectQuery} key={q.id} />)}</div>}

          <div className="mono panel-title" style={{ margin: '16px 0 8px' }}>
            PADRÕES DETETADOS {flaggedPatterns.length > 0 ? `(${flaggedPatterns.length})` : ''}
          </div>
          {flaggedPatterns.length === 0
            ? <div className="empty-state">Sem padrões repetidos ainda.</div>
            : (
              <div className="feed-list">
                {flaggedPatterns.map(p => (
                  <div className="feed-item" style={{ borderLeftColor: '#4f8fe0' }} key={p.id}>
                    <div className="row" style={{ justifyContent: 'space-between' }}>
                      <span className="mono feed-item-tag" style={{ color: '#4f8fe0' }}>{p.occurrence_count}x</span>
                    </div>
                    <div className="feed-item-text">{p.example_question}</div>
                  </div>
                ))}
              </div>
            )}
        </div>

        <div style={{ flex: 1 }}>
          <div className="mono panel-title" style={{ marginBottom: 8 }}>
            RESPOSTAS PENDENTES {pendingDrafts.length > 0 ? `(${pendingDrafts.length})` : ''}
          </div>
          {recentDrafts.length === 0
            ? <div className="empty-state">Sem rascunhos de resposta ainda.</div>
            : recentDrafts.map(draft => <DraftRow draft={draft} apiBase={apiBase} onUpdated={onDraftUpdated} key={draft.id} />)}
        </div>
      </div>
    </div>
  );
}

export default CustomerPanel;
