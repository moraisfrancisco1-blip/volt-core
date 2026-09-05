import React from 'react';

function timeAgo(isoString) {
  if (!isoString) return '—';
  const diffMs = Date.now() - new Date(isoString).getTime();
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 1) return 'agora';
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

function eventTag(event) {
  if (event.status === 'resolved') return { tag: 'OK', color: '#8fc48a' };
  if (event.priority === 'P1') return { tag: 'P1', color: '#d9614f' };
  if (event.priority === 'P2') return { tag: 'P2', color: '#e0793c' };
  if (event.priority) return { tag: event.priority, color: '#8a9bd8' };
  return { tag: (event.severity || 'INFO').toUpperCase(), color: '#8a9bd8' };
}

function EventFeed({ events, limit = 6, onSelect }) {
  const items = limit ? events.slice(0, limit) : events;
  return (
    <div className="panel event-feed-panel">
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
        <div className="panel-title" style={{ margin: 0 }}>FEED DE EVENTOS</div>
        <div className="row" style={{ gap: 5 }}>
          <span className="live-dot" />
          <span className="mono live-label">LIVE</span>
        </div>
      </div>
      <div className="feed-list">
        {items.length === 0
          ? <div className="empty-state">À espera do primeiro evento.</div>
          : items.map(event => {
              const { tag, color } = eventTag(event);
              return (
                <div
                  className={`feed-item${onSelect ? ' clickable-row' : ''}`}
                  style={{ borderLeftColor: color }}
                  key={event.id}
                  onClick={onSelect ? () => onSelect(event) : undefined}
                >
                  <div className="row" style={{ justifyContent: 'space-between' }}>
                    <span className="mono feed-item-tag" style={{ color }}>{tag}</span>
                    <span className="mono feed-item-time">{timeAgo(event.received_at || event.created_at)}</span>
                  </div>
                  <div className="feed-item-text">{event.title || event.message}</div>
                </div>
              );
            })}
      </div>
    </div>
  );
}

export default EventFeed;
