import React from 'react';
import EventFeed from '../EventFeed.jsx';

function EventsView({ events, onSelect }) {
  return (
    <div className="view-row">
      <div className="view-panel">
        <EventFeed events={events} limit={0} onSelect={onSelect} />
      </div>
    </div>
  );
}

export default EventsView;
