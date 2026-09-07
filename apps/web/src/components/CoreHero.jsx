import React from 'react';

const ACCENT = '#f0b429';
const ACCENT2 = '#4f8fe0';
// Same convention as AgentGrid's STATE_COLOR -- one status palette across the dashboard.
const STATE_COLOR = { working: '#f0b429', error: '#d9614f', idle: '#7d7062' };

const VIEW_W = 900, VIEW_H = 300;
const CX = VIEW_W / 2, CY = VIEW_H / 2;
const RX = 300, RY = 108;

// Fixed slot layout, evenly spaced by angle around an ellipse (wide, to fit the hero
// panel's fixed height but flexible width) -- one slot per agent, in AGENT_ORDER's order.
const SLOT_ANGLES = [-90, -54, -18, 18, 54, 90, 126, 162, 198, 234].map(deg => (deg * Math.PI) / 180);
const SLOTS = SLOT_ANGLES.map(a => ({ x: CX + RX * Math.cos(a), y: CY + RY * Math.sin(a) }));

function labelAnchor(slot) {
  const dx = slot.x - CX, dy = slot.y - CY;
  if (Math.abs(dy) > RY * 0.85) return { anchor: 'middle', dx: 0, dy: dy < 0 ? -14 : 20 };
  return dx >= 0 ? { anchor: 'start', dx: 12, dy: 4 } : { anchor: 'end', dx: -12, dy: 4 };
}

function CoreHero({ agents }) {
  const nodes = SLOTS.map((slot, i) => {
    const agent = agents?.[i];
    const color = agent ? (STATE_COLOR[agent.state] || STATE_COLOR.idle) : STATE_COLOR.idle;
    return { ...slot, label: agent?.label || '—', color, working: agent?.state === 'working' };
  });

  return (
    <div className="panel hero-panel">
      <div className="hero-glow" style={{ background: `radial-gradient(circle at 50% 50%, ${ACCENT}1c, transparent 60%), radial-gradient(circle at 50% 50%, ${ACCENT2}18, transparent 70%)` }} />
      <svg className="hero-network" viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} preserveAspectRatio="xMidYMid meet">
        <ellipse cx={CX} cy={CY} rx={RX} ry={RY} fill="none" stroke={ACCENT2} strokeOpacity="0.16" strokeWidth="1" strokeDasharray="2 6" />
        <ellipse cx={CX} cy={CY} rx={RX * 0.62} ry={RY * 0.62} fill="none" stroke={ACCENT} strokeOpacity="0.12" strokeWidth="1" />

        {nodes.map((node, i) => (
          <line key={`spoke-${i}`} x1={CX} y1={CY} x2={node.x} y2={node.y} stroke={node.color} strokeOpacity="0.35" strokeWidth="1" strokeDasharray="1 4" />
        ))}

        <circle cx={CX} cy={CY} r="30" fill="rgba(240,180,60,0.08)" stroke={ACCENT} strokeWidth="1.3" />
        <path d="M13 2 4 14h6l-1 8 9-12h-6z" fill={ACCENT} transform={`translate(${CX - 8}, ${CY - 9}) scale(0.7)`} />

        {nodes.map((node, i) => {
          const { anchor, dx, dy } = labelAnchor(node);
          return (
            <g key={`node-${i}`} className={node.working ? 'hero-node-working' : undefined}>
              <circle cx={node.x} cy={node.y} r="6.5" fill="#120e0a" stroke={node.color} strokeWidth="1.6" />
              <circle cx={node.x} cy={node.y} r="2" fill={node.color} />
              <text x={node.x + dx} y={node.y + dy} textAnchor={anchor} className="mono hero-node-label" fill={node.color}>
                {node.label}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="hero-label">
        <div className="display hero-title">VOLTCORE</div>
        <div className="mono hero-subtitle">NÚCLEO DE IA · v1.0</div>
      </div>
    </div>
  );
}

export default React.memo(CoreHero);
