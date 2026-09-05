import React from 'react';
import EscalationQueue from '../EscalationQueue.jsx';

function EscalationsView({ escalations, onSelect }) {
  return (
    <div className="view-row">
      <div className="view-panel">
        <EscalationQueue escalations={escalations} limit={0} onSelect={onSelect} />
      </div>
    </div>
  );
}

export default EscalationsView;
