import React from 'react';
import IntegrationsPanel from '../IntegrationsPanel.jsx';
import SystemMonitor from '../SystemMonitor.jsx';

function IntegrationsView({ integrations, railwayConfigured }) {
  return (
    <div className="view-row">
      <IntegrationsPanel integrations={integrations} />
      <SystemMonitor railwayConfigured={railwayConfigured} />
    </div>
  );
}

export default IntegrationsView;
