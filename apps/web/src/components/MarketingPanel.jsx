import React, { useState } from 'react';

const FORMAT_LABEL = {
  blog: 'BLOG',
  linkedin_post: 'LINKEDIN',
  twitter_post: 'TWITTER/X',
  instagram_carousel: 'INSTAGRAM',
};

function ContentRow({ content, apiBase, onUpdated, onRepurposed }) {
  const [approveState, setApproveState] = useState('idle'); // idle | approving | done | error
  const [repurposeState, setRepurposeState] = useState('idle'); // idle | running | done | error

  const approve = async () => {
    setApproveState('approving');
    try {
      const response = await fetch(`${apiBase}/api/marketing-content/${content.id}/approve`, { method: 'POST' });
      const payload = await response.json();
      onUpdated(payload);
      setApproveState(payload.status === 'approved' ? 'done' : 'error');
    } catch {
      setApproveState('error');
    }
    setTimeout(() => setApproveState('idle'), 4000);
  };

  const repurpose = async () => {
    setRepurposeState('running');
    try {
      const response = await fetch(`${apiBase}/api/marketing-content/${content.id}/repurpose`, { method: 'POST' });
      const payload = await response.json();
      setRepurposeState(payload.triggered ? 'done' : 'error');
      if (payload.triggered) onRepurposed();
    } catch {
      setRepurposeState('error');
    }
    setTimeout(() => setRepurposeState('idle'), 4000);
  };

  const isPending = content.status === 'pending_approval';
  const approveLabel = approveState === 'approving' ? 'A APROVAR…' : approveState === 'done' ? 'APROVADO' : approveState === 'error' ? 'FALHOU' : 'Aprovar';
  const repurposeLabel = repurposeState === 'running' ? 'A GERAR…' : repurposeState === 'done' ? 'VARIANTES PEDIDAS' : repurposeState === 'error' ? 'FALHOU' : 'Repurpose';

  return (
    <div className="panel-row-item" style={{ padding: 12, marginBottom: 8 }}>
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 6 }}>
        <span className="agent-card-name">{content.title}</span>
        <span className="mono feed-item-time">{content.status === 'pending_approval' ? 'pendente de aprovação' : 'aprovado'}</span>
      </div>
      <div className="row" style={{ gap: 8, marginBottom: 6 }}>
        <span className="mono feed-item-tag" style={{ color: '#f0b429' }}>{FORMAT_LABEL[content.format] || content.format}</span>
        {content.parent_content_id && <span className="mono feed-item-time">variante de #{content.parent_content_id}</span>}
      </div>
      <div className="feed-item-text" style={{ marginBottom: 8, whiteSpace: 'pre-wrap' }}>{content.body}</div>
      {content.source_facts && <div className="mono feed-item-time" style={{ marginBottom: 8 }}>Fontes: {content.source_facts}</div>}
      <div className="row" style={{ gap: 8 }}>
        {isPending && (
          <button
            type="button"
            className="row panel-row-item command-row actionable command-row-button"
            style={{ opacity: approveState === 'approving' ? 0.7 : 1, flex: 1 }}
            onClick={approve}
            disabled={approveState === 'approving'}
          >
            <span className="command-label">{approveLabel}</span>
          </button>
        )}
        {content.content_type === 'blog_post' && (
          <button
            type="button"
            className="row panel-row-item command-row actionable command-row-button"
            style={{ opacity: repurposeState === 'running' ? 0.7 : 1, flex: 1 }}
            onClick={repurpose}
            disabled={repurposeState === 'running'}
          >
            <span className="command-label">{repurposeLabel}</span>
          </button>
        )}
      </div>
    </div>
  );
}

function MarketingPanel({ content, performance, apiBase, onContentUpdated, onRepurposeRequested }) {
  const items = (content || []).slice(0, 6);

  return (
    <div className="panel">
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
        <div className="panel-title" style={{ margin: 0 }}>MARKETING</div>
        <span className="mono feed-item-time">{performance?.summary || 'sem dados de performance ainda'}</span>
      </div>
      {items.length === 0
        ? <div className="empty-state">Sem conteúdo gerado ainda.</div>
        : items.map(item => (
            <ContentRow
              content={item}
              apiBase={apiBase}
              onUpdated={onContentUpdated}
              onRepurposed={onRepurposeRequested}
              key={item.id}
            />
          ))}
    </div>
  );
}

export default MarketingPanel;
