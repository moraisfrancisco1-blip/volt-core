import React, { useEffect, useRef } from 'react';

const ACCENT = '#f0b429';
const ACCENT2 = '#4f8fe0';
// Same convention as AgentGrid's STATE_COLOR -- one status palette across the dashboard.
const STATE_COLOR = { working: '#f0b429', error: '#d9614f', idle: '#7d7062' };

const VIEW_W = 900, VIEW_H = 300;
const CX = VIEW_W / 2, CY = VIEW_H / 2;
const RX = 300, RY = 108;
const RX2 = RX * 0.62, RY2 = RY * 0.62;

// Fixed slot layout, evenly spaced by angle around an ellipse (wide, to fit the hero
// panel's fixed height but flexible width) -- one slot per agent, in AGENT_ORDER's order.
const SLOT_ANGLES = [-90, -54, -18, 18, 54, 90, 126, 162, 198, 234].map(deg => (deg * Math.PI) / 180);
const SLOTS = SLOT_ANGLES.map(a => ({ x: CX + RX * Math.cos(a), y: CY + RY * Math.sin(a) }));

function ellipsePath(rx, ry) {
  return `M${CX + rx},${CY} A${rx},${ry} 0 1 1 ${CX - rx},${CY} A${rx},${ry} 0 1 1 ${CX + rx},${CY} Z`;
}
const RING_PATH = ellipsePath(RX, RY);
const RING2_PATH = ellipsePath(RX2, RY2);

// A gently tapered sine-wave path from the core out to a node -- two of these, mirrored
// in phase, is what makes the connection read as an orbiting electron pair rather than a
// dot sliding down a wire. Coordinates are relative to the core (animateMotion moves an
// element by these offsets from its own start position), amplitude tapers to 0 at both
// ends so the wave doesn't overshoot the node or wobble at the core.
function electronPath(dx, dy, amplitude, phase) {
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len, uy = dy / len;
  const px = -uy, py = ux; // perpendicular unit vector
  const segments = 14;
  const points = [];
  for (let i = 0; i <= segments; i++) {
    const t = i / segments;
    const envelope = Math.sin(t * Math.PI); // 0 at both ends, peak at the middle
    const offset = amplitude * envelope * Math.sin(t * Math.PI * 3 + phase);
    points.push([dx * t + px * offset, dy * t + py * offset]);
  }
  return `M${points.map(p => p.join(',')).join(' L')}`;
}

function labelAnchor(slot) {
  const dx = slot.x - CX, dy = slot.y - CY;
  if (Math.abs(dy) > RY * 0.85) return { anchor: 'middle', dx: 0, dy: dy < 0 ? -14 : 20 };
  return dx >= 0 ? { anchor: 'start', dx: 12, dy: 4 } : { anchor: 'end', dx: -12, dy: 4 };
}

// Cursor-driven 3D tilt: the whole diagram reads as a tilted glass panel that leans
// toward the pointer, smoothed frame-by-frame (lerp) rather than snapping -- the same
// smoothing approach the old canvas hero used for its parallax, just driving a CSS
// transform instead of a canvas translate.
function useTiltParallax(containerRef, targetRef) {
  useEffect(() => {
    const container = containerRef.current;
    const target = targetRef.current;
    if (!container || !target) return;
    let mx = 0, my = 0, curX = 0, curY = 0, hover = false, raf = null;

    const onMove = ev => {
      const rect = container.getBoundingClientRect();
      mx = Math.max(-1, Math.min(1, ((ev.clientX - rect.left) / rect.width) * 2 - 1));
      my = Math.max(-1, Math.min(1, ((ev.clientY - rect.top) / rect.height) * 2 - 1));
    };
    const onEnter = () => { hover = true; };
    const onLeave = () => { hover = false; mx = 0; my = 0; };
    container.addEventListener('mousemove', onMove);
    container.addEventListener('mouseenter', onEnter);
    container.addEventListener('mouseleave', onLeave);

    const loop = () => {
      curX += (mx - curX) * 0.06;
      curY += (my - curY) * 0.06;
      const rotY = curX * 11, rotX = -curY * 8;
      target.style.transform = `perspective(1000px) rotateX(${rotX}deg) rotateY(${rotY}deg) scale(${hover ? 1.015 : 1})`;
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(raf);
      container.removeEventListener('mousemove', onMove);
      container.removeEventListener('mouseenter', onEnter);
      container.removeEventListener('mouseleave', onLeave);
    };
  }, [containerRef, targetRef]);
}

function CoreHero({ agents }) {
  const panelRef = useRef(null);
  const svgRef = useRef(null);
  useTiltParallax(panelRef, svgRef);

  const nodes = SLOTS.map((slot, i) => {
    const agent = agents?.[i];
    const state = agent?.state && STATE_COLOR[agent.state] ? agent.state : 'idle';
    return { ...slot, label: agent?.label || '—', color: STATE_COLOR[state], state, working: state === 'working' };
  });

  return (
    <div className="panel hero-panel" ref={panelRef}>
      <div className="hero-glow" style={{ background: `radial-gradient(circle at 50% 50%, ${ACCENT}1c, transparent 60%), radial-gradient(circle at 50% 50%, ${ACCENT2}18, transparent 70%)` }} />
      <svg ref={svgRef} className="hero-network" viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} preserveAspectRatio="xMidYMid meet">
        <defs>
          <filter id="hero-glow-filter" x="-200%" y="-200%" width="500%" height="500%">
            <feGaussianBlur stdDeviation="2.4" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <path className="hero-ring hero-ring-outer" d={RING_PATH} fill="none" stroke={ACCENT2} strokeOpacity="0.22" strokeWidth="1" strokeDasharray="2 10" />
        <path className="hero-ring hero-ring-inner" d={RING2_PATH} fill="none" stroke={ACCENT} strokeOpacity="0.16" strokeWidth="1" strokeDasharray="1 7" />

        {/* Data flowing around the inner orbit -- two dots, offset in time, tracing the ring continuously. */}
        {[0, 0.5].map(offset => (
          <circle key={`orbit-dot-${offset}`} r="2.2" fill={ACCENT} opacity="0.85" filter="url(#hero-glow-filter)">
            <animateMotion dur="9s" begin={`${-offset * 9}s`} repeatCount="indefinite" path={RING2_PATH} />
          </circle>
        ))}

        {/* Faint bond line as a guide, current visibly flowing along it via a scrolling
            dash pattern -- the connection itself looks live, not just the electrons on it. */}
        {nodes.map((node, i) => (
          <line key={`spoke-${i}`} className="hero-spoke" x1={CX} y1={CY} x2={node.x} y2={node.y} stroke={node.color} strokeOpacity="0.22" strokeWidth="1" strokeDasharray="1 5" />
        ))}

        {/* Two electrons per bond, weaving around the connection axis in a tapered sine
            wave with opposite phase -- reads as an orbiting electron pair binding the
            core to each agent, not a dot sliding down a wire. Faster and brighter while
            that agent's state is "working". */}
        {nodes.map((node, i) => {
          const dx = node.x - CX, dy = node.y - CY;
          const dur = node.working ? 1.4 : 3.2;
          return (
            <g key={`electrons-${i}`} transform={`translate(${CX},${CY})`}>
              {[0, Math.PI].map((phase, e) => (
                <circle key={e} r={node.working ? 2.3 : 1.8} fill={e === 0 ? '#fff8ec' : node.color} filter="url(#hero-glow-filter)">
                  <animateMotion dur={`${dur}s`} begin={`${i * 0.22 + e * (dur / 2)}s`} repeatCount="indefinite" path={electronPath(dx, dy, 9, phase)} />
                </circle>
              ))}
            </g>
          );
        })}

        <g className="hero-hub">
          <circle cx={CX} cy={CY} r="30" fill="rgba(240,180,60,0.08)" stroke={ACCENT} strokeWidth="1.3" />
          <circle className="hero-hub-ring" cx={CX} cy={CY} r="40" fill="none" stroke={ACCENT} strokeOpacity="0.4" strokeWidth="1" strokeDasharray="4 6" />
          <path d="M13 2 4 14h6l-1 8 9-12h-6z" fill={ACCENT} transform={`translate(${CX - 8}, ${CY - 9}) scale(0.7)`} />
        </g>

        {nodes.map((node, i) => {
          const { anchor, dx, dy } = labelAnchor(node);
          return (
            <g key={`node-${i}`} className={`hero-node hero-node-${node.state}`}>
              <circle className="hero-node-halo" cx={node.x} cy={node.y} r="6.5" fill="none" stroke={node.color} strokeWidth="1.6" style={{ animationDelay: `${i * 0.18}s` }} />
              <circle cx={node.x} cy={node.y} r="6.5" fill="#120e0a" stroke={node.color} strokeWidth="1.6" />
              <circle className="hero-node-dot" cx={node.x} cy={node.y} r="2" fill={node.color} />
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
