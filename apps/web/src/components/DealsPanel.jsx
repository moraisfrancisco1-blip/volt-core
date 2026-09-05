import React, { useState } from 'react';

const STAGE_LABEL = {
  qualified: 'QUALIFICADO',
  proposal_prepared: 'PROPOSTA PREPARADA',
  negotiating: 'EM NEGOCIAÇÃO',
  closed_won: 'FECHADO GANHO',
  closed_lost: 'FECHADO PERDIDO',
};
const STAGE_ORDER = ['qualified', 'proposal_prepared', 'negotiating', 'closed_won', 'closed_lost'];

function ProposalRow({ proposal, apiBase, onUpdated }) {
  const [state, setState] = useState('idle'); // idle | sending | done | error

  const approveAndSend = async () => {
    setState('sending');
    try {
      const response = await fetch(`${apiBase}/api/deal-proposals/${proposal.id}/approve-and-send`, { method: 'POST' });
      const payload = await response.json();
      onUpdated(payload);
      setState(payload.status === 'approved_sent' ? 'done' : 'error');
    } catch {
      setState('error');
    }
    setTimeout(() => setState('idle'), 4000);
  };

  const isPending = proposal.status === 'pending_approval';
  const label = state === 'sending' ? 'A ENVIAR…' : state === 'done' ? 'ENVIADO' : state === 'error' ? 'FALHOU' : 'Aprovar e Enviar';

  return (
    <div className="panel-row-item" style={{ padding: 12, marginBottom: 8 }}>
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 6 }}>
        <span className="agent-card-name">Deal #{proposal.deal_id}</span>
        <span className="mono feed-item-time">{proposal.price_summary}</span>
      </div>
      <div className="feed-item-text" style={{ marginBottom: 8, whiteSpace: 'pre-wrap' }}>{proposal.body}</div>
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

function CloseSuggestionRow({ deal, apiBase, onUpdated }) {
  const [state, setState] = useState('idle'); // idle | confirming | error

  const confirm = async stage => {
    setState('confirming');
    try {
      const response = await fetch(`${apiBase}/api/deals/${deal.id}/confirm-stage`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stage }),
      });
      const payload = await response.json();
      onUpdated(payload);
    } catch {
      setState('error');
      return;
    }
    setState('idle');
  };

  return (
    <div className="panel-row-item" style={{ padding: 12, marginBottom: 8 }}>
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 6 }}>
        <span className="agent-card-name">Deal #{deal.id}</span>
        <span className="mono feed-item-time">sugestão: {STAGE_LABEL[deal.suggested_stage] || deal.suggested_stage}</span>
      </div>
      <div className="feed-item-text" style={{ marginBottom: 8 }}>{deal.suggested_stage_reason}</div>
      <div className="row" style={{ gap: 8 }}>
        <button
          type="button"
          className="row panel-row-item command-row actionable command-row-button"
          style={{ opacity: state === 'confirming' ? 0.7 : 1 }}
          onClick={() => confirm('closed_won')}
          disabled={state === 'confirming'}
        >
          <span className="command-label">Confirmar Fechado Ganho</span>
        </button>
        <button
          type="button"
          className="row panel-row-item command-row actionable command-row-button"
          style={{ opacity: state === 'confirming' ? 0.7 : 1 }}
          onClick={() => confirm('closed_lost')}
          disabled={state === 'confirming'}
        >
          <span className="command-label">Confirmar Fechado Perdido</span>
        </button>
      </div>
    </div>
  );
}

function DealsPanel({ deals, proposals, apiBase, onProposalUpdated, onDealUpdated, onSelectDeal }) {
  const stageCounts = STAGE_ORDER.map(stage => ({ stage, count: (deals || []).filter(d => d.stage === stage).length }));
  const pendingProposals = (proposals || []).filter(p => p.status === 'pending_approval').slice(0, 4);
  const staleDeals = (deals || []).filter(d => d.stale).slice(0, 4);
  const suggestedDeals = (deals || []).filter(d => d.suggested_stage).slice(0, 4);

  return (
    <div className="panel">
      <div className="panel-title">DEALS</div>

      <div className="market-intel-grid" style={{ marginBottom: 16 }}>
        {stageCounts.map(({ stage, count }) => (
          <div className="panel-row-item" style={{ padding: 12 }} key={stage}>
            <div className="mono panel-title" style={{ marginBottom: 6 }}>{STAGE_LABEL[stage]}</div>
            <div className="feed-item-text">{count}</div>
          </div>
        ))}
      </div>

      <div className="row" style={{ gap: 16, alignItems: 'flex-start' }}>
        <div style={{ flex: 1 }}>
          <div className="mono panel-title" style={{ marginBottom: 8 }}>
            PROPOSTAS PENDENTES {pendingProposals.length > 0 ? `(${pendingProposals.length})` : ''}
          </div>
          {pendingProposals.length === 0
            ? <div className="empty-state">Sem propostas pendentes.</div>
            : pendingProposals.map(p => <ProposalRow proposal={p} apiBase={apiBase} onUpdated={onProposalUpdated} key={p.id} />)}
        </div>

        <div style={{ flex: 1 }}>
          <div className="mono panel-title" style={{ marginBottom: 8 }}>
            SUGESTÕES DE FECHO {suggestedDeals.length > 0 ? `(${suggestedDeals.length})` : ''}
          </div>
          {suggestedDeals.length === 0
            ? <div className="empty-state">Sem sugestões de fecho pendentes.</div>
            : suggestedDeals.map(d => <CloseSuggestionRow deal={d} apiBase={apiBase} onUpdated={onDealUpdated} key={d.id} />)}

          <div className="mono panel-title" style={{ margin: '16px 0 8px' }}>
            PARADOS HÁ MAIS TEMPO {staleDeals.length > 0 ? `(${staleDeals.length})` : ''}
          </div>
          {staleDeals.length === 0
            ? <div className="empty-state">Sem deals parados.</div>
            : (
              <div className="feed-list">
                {staleDeals.map(d => (
                  <div
                    className={`feed-item${onSelectDeal ? ' clickable-row' : ''}`}
                    style={{ borderLeftColor: '#e0793c' }}
                    key={d.id}
                    onClick={onSelectDeal ? () => onSelectDeal(d) : undefined}
                  >
                    <div className="row" style={{ justifyContent: 'space-between' }}>
                      <span className="mono feed-item-tag" style={{ color: '#e0793c' }}>{STAGE_LABEL[d.stage]}</span>
                    </div>
                    <div className="feed-item-text">Deal #{d.id} -- precisa de atenção</div>
                  </div>
                ))}
              </div>
            )}
        </div>
      </div>
    </div>
  );
}

export default DealsPanel;
