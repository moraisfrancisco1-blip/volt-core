import React, { useState } from 'react';

const LEAD_TYPE_LABEL = { consumer_inbound: 'CONSUMIDOR', b2b_partner: 'PARCEIRO B2B' };

function DraftRow({ draft, apiBase, onUpdated }) {
  const [state, setState] = useState('idle'); // idle | sending | done | error

  const approveAndSend = async () => {
    setState('sending');
    try {
      const response = await fetch(`${apiBase}/api/sales-outreach-drafts/${draft.id}/approve-and-send`, { method: 'POST' });
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

function LeadRow({ lead, onSelect }) {
  return (
    <div
      className={`feed-item${onSelect ? ' clickable-row' : ''}`}
      style={{ borderLeftColor: '#f0b429' }}
      onClick={onSelect ? () => onSelect(lead) : undefined}
    >
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <span className="mono feed-item-tag" style={{ color: '#f0b429' }}>{LEAD_TYPE_LABEL[lead.lead_type] || lead.lead_type}</span>
        <span className="mono feed-item-time">{lead.fit_score != null ? `fit ${Math.round(lead.fit_score * 100)}%` : '—'}</span>
      </div>
      <div className="feed-item-text">{lead.name} — {lead.qualification_summary || 'sem resumo ainda'}</div>
    </div>
  );
}

function SalesPanel({ leads, drafts, apiBase, onDraftUpdated, onSelectLead }) {
  const qualifiedLeads = (leads || []).filter(l => l.status === 'qualified').slice(0, 6);
  const pendingDrafts = (drafts || []).filter(d => d.status === 'pending_approval');
  const recentDrafts = (drafts || []).slice(0, 4);

  return (
    <div className="panel">
      <div className="panel-title">SALES</div>
      <div className="row" style={{ gap: 16, alignItems: 'flex-start' }}>
        <div style={{ flex: 1 }}>
          <div className="mono panel-title" style={{ marginBottom: 8 }}>LEADS QUALIFICADOS</div>
          {qualifiedLeads.length === 0
            ? <div className="empty-state">Sem leads qualificados ainda.</div>
            : <div className="feed-list">{qualifiedLeads.map(lead => <LeadRow lead={lead} onSelect={onSelectLead} key={lead.id} />)}</div>}
        </div>
        <div style={{ flex: 1 }}>
          <div className="mono panel-title" style={{ marginBottom: 8 }}>
            OUTREACH B2B {pendingDrafts.length > 0 ? `(${pendingDrafts.length} pendente${pendingDrafts.length > 1 ? 's' : ''})` : ''}
          </div>
          {recentDrafts.length === 0
            ? <div className="empty-state">Sem rascunhos de outreach ainda.</div>
            : recentDrafts.map(draft => <DraftRow draft={draft} apiBase={apiBase} onUpdated={onDraftUpdated} key={draft.id} />)}
        </div>
      </div>
    </div>
  );
}

export default SalesPanel;
