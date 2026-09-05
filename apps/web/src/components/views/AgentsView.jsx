import React, { useState } from 'react';
import AgentGrid from '../AgentGrid.jsx';

const AGENT_INVESTIGATION_TYPE = {
  volt: 'voice_call_failure',
  dev_debug: 'code_diagnosis',
  database: 'database_diagnosis',
  finance: 'finance_diagnosis',
};

function AgentsView({ agents, investigations, salesLeads, deals, marketingContent, onSelectInvestigation, onSelectLead, onSelectDeal, onSelectContent }) {
  const [filter, setFilter] = useState(null); // agent id or null (all)

  const visibleAgents = filter ? agents.filter(a => a.id === filter) : agents;

  let rows = [];
  if (!filter || AGENT_INVESTIGATION_TYPE[filter]) {
    const type = filter ? AGENT_INVESTIGATION_TYPE[filter] : null;
    rows = investigations
      .filter(i => !type || i.investigation_type === type)
      .slice(0, 30)
      .map(i => ({ key: `inv-${i.id}`, tag: i.investigation_type, text: (i.status === 'failed' ? i.error : i.hypothesis) || 'sem resumo', onClick: () => onSelectInvestigation(i) }));
  } else if (filter === 'sales') {
    rows = salesLeads.slice(0, 30).map(l => ({ key: `lead-${l.id}`, tag: l.lead_type, text: `${l.name} — ${l.qualification_summary || 'sem resumo'}`, onClick: () => onSelectLead(l) }));
  } else if (filter === 'deals') {
    rows = deals.slice(0, 30).map(d => ({ key: `deal-${d.id}`, tag: d.stage, text: `Deal #${d.id}`, onClick: () => onSelectDeal(d) }));
  } else if (filter === 'marketing') {
    rows = marketingContent.slice(0, 30).map(c => ({ key: `content-${c.id}`, tag: c.format, text: c.title, onClick: () => onSelectContent(c) }));
  }

  return (
    <div className="view-row" style={{ flexDirection: 'column' }}>
      <div className="view-panel" style={{ flex: '0 0 auto' }}>
        <AgentGrid agents={visibleAgents} onSelect={agent => setFilter(prev => (prev === agent.id ? null : agent.id))} />
      </div>
      <div className="panel view-panel">
        <div className="row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
          <div className="panel-title" style={{ margin: 0 }}>
            {filter ? `HISTÓRICO — ${filter.toUpperCase()}` : 'HISTÓRICO — TODOS OS AGENTES'}
          </div>
          {filter && <button type="button" className="mono" style={{ background: 'none', border: 'none', color: '#8a7c68', cursor: 'pointer', fontSize: 10 }} onClick={() => setFilter(null)}>limpar filtro</button>}
        </div>
        {rows.length === 0
          ? <div className="empty-state">Sem histórico ainda.</div>
          : (
            <div className="feed-list">
              {rows.map(row => (
                <div className="feed-item clickable-row" style={{ borderLeftColor: '#f0b429' }} key={row.key} onClick={row.onClick}>
                  <span className="mono feed-item-tag" style={{ color: '#f0b429' }}>{row.tag}</span>
                  <div className="feed-item-text">{row.text}</div>
                </div>
              ))}
            </div>
          )}
      </div>
    </div>
  );
}

export default AgentsView;
