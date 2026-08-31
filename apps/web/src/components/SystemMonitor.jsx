import React from 'react';

const GAUGES = [
  { key: 'cpu', label: 'CPU' },
  { key: 'ram', label: 'RAM' },
  { key: 'disk', label: 'DISCO' },
];

const CIRCUMFERENCE = 188.5;

function SystemMonitor({ railwayConfigured }) {
  return (
    <div className="panel" style={{ flex: 1 }}>
      <div className="panel-title">MONITOR DO SISTEMA · RAILWAY</div>
      <div className="row gauges-row">
        {GAUGES.map(g => (
          <div style={{ textAlign: 'center' }} key={g.key}>
            <svg width="72" height="72" viewBox="0 0 72 72">
              <circle cx="36" cy="36" r="30" fill="none" stroke="rgba(240,180,60,0.10)" strokeWidth="6" />
              {railwayConfigured && (
                <circle cx="36" cy="36" r="30" fill="none" stroke="#f0b429" strokeWidth="6" strokeLinecap="round" strokeDasharray={CIRCUMFERENCE} strokeDashoffset={CIRCUMFERENCE} transform="rotate(-90 36 36)" />
              )}
              <text x="36" y="41" textAnchor="middle" fontFamily="JetBrains Mono, monospace" fontSize="13" fill={railwayConfigured ? '#f5ede0' : '#7d7062'}>N/D</text>
            </svg>
            <div className="mono gauge-label">{g.label}</div>
          </div>
        ))}
      </div>
      {!railwayConfigured && (
        <div className="mono empty-state" style={{ textAlign: 'center', padding: '4px 0 0' }}>Requer RAILWAY_TOKEN</div>
      )}
    </div>
  );
}

export default SystemMonitor;
