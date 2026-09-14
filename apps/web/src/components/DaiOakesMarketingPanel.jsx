import React, { useState } from 'react';

const FORMAT_LABEL = {
  instagram_post: 'INSTAGRAM',
  facebook_post: 'FACEBOOK',
  blog_post: 'BLOG',
};

function ContentRow({ content, apiBase, onUpdated, onSelect }) {
  const [approveState, setApproveState] = useState('idle'); // idle | approving | done | error

  const approve = async () => {
    setApproveState('approving');
    try {
      const response = await fetch(`${apiBase}/api/dai-oakes-marketing-content/${content.id}/approve`, { method: 'POST' });
      const payload = await response.json();
      onUpdated(payload);
      setApproveState(payload.status === 'approved' ? 'done' : 'error');
    } catch {
      setApproveState('error');
    }
    setTimeout(() => setApproveState('idle'), 4000);
  };

  const isPending = content.status === 'pending_approval';
  const approveLabel = approveState === 'approving' ? 'A APROVAR…' : approveState === 'done' ? 'APROVADO' : approveState === 'error' ? 'FALHOU' : 'Aprovar';

  return (
    <div className="panel-row-item" style={{ padding: 12, marginBottom: 8 }}>
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 6 }}>
        <span className={`agent-card-name${onSelect ? ' clickable-row' : ''}`} onClick={onSelect ? () => onSelect(content) : undefined}>{content.title}</span>
        <span className="mono feed-item-time">{content.status === 'pending_approval' ? 'pendente de aprovação' : 'aprovado'}</span>
      </div>
      <div className="row" style={{ gap: 8, marginBottom: 6 }}>
        <span className="mono feed-item-tag" style={{ color: '#e0793c' }}>{FORMAT_LABEL[content.format] || content.format}</span>
      </div>
      <div className="feed-item-text" style={{ marginBottom: 8, whiteSpace: 'pre-wrap' }}>{content.body}</div>
      {content.source_facts && <div className="mono feed-item-time" style={{ marginBottom: 8 }}>Fontes: {content.source_facts}</div>}
      {isPending && (
        <button
          type="button"
          className="row panel-row-item command-row actionable command-row-button"
          style={{ opacity: approveState === 'approving' ? 0.7 : 1 }}
          onClick={approve}
          disabled={approveState === 'approving'}
        >
          <span className="command-label">{approveLabel}</span>
        </button>
      )}
    </div>
  );
}

function DaiOakesMarketingPanel({ content, apiBase, onContentUpdated, onSelectContent }) {
  const items = (content || []).slice(0, 6);

  return (
    <div className="panel">
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
        <div className="panel-title" style={{ margin: 0 }}>DAI OAKES · MARKETING</div>
        <span className="mono feed-item-time">só factos do site público -- nunca dados de pacientes</span>
      </div>
      {items.length === 0
        ? <div className="empty-state">Sem conteúdo gerado ainda.</div>
        : items.map(item => (
            <ContentRow
              content={item}
              apiBase={apiBase}
              onUpdated={onContentUpdated}
              onSelect={onSelectContent}
              key={item.id}
            />
          ))}
    </div>
  );
}

export default DaiOakesMarketingPanel;
