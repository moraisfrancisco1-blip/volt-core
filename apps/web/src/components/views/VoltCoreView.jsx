import React from 'react';
import SystemOverview from '../SystemOverview.jsx';
import EventFeed from '../EventFeed.jsx';
import InvestigationHistory from '../InvestigationHistory.jsx';

function VoltCoreView({ investigations, twilioConfigured, agentsStatus, systemOk, events, fetchLimit, onSelectEvent }) {
  return (
    <div className="view-row" style={{ flexDirection: 'column' }}>
      <div className="view-row">
        <SystemOverview
          investigationCount={investigations.length}
          twilioConfigured={twilioConfigured}
          agentsStatus={agentsStatus}
          systemOk={systemOk}
          iconColor="#f0b429"
        />
        <InvestigationHistory investigations={investigations} fetchLimit={fetchLimit} />
      </div>
      <div className="view-panel">
        <EventFeed events={events} limit={0} onSelect={onSelectEvent} />
      </div>
    </div>
  );
}

export default VoltCoreView;
