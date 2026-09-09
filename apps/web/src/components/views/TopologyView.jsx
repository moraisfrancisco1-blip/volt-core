import React, { useMemo, useState } from 'react';
import VoltMark from '../VoltMark.jsx';

/* ---------------------------------------------------------------------------
 * Mapa de topologia -- os mesmos agentes do Centro de Comando, mas agrupados
 * por empresa em sectores separados em vez de num anel único.
 *
 * COMPANIES é o ÚNICO sítio a editar quando um agente muda de empresa ou uma
 * empresa nova aparece: sectores, cores, ligações e legenda são todos derivados
 * daqui. Um agente que o backend não devolva é simplesmente ignorado, e uma
 * empresa sem agentes presentes não desenha sector nenhum -- por isso isto não
 * parte quando o AGENT_ORDER do main.jsx muda.
 * ------------------------------------------------------------------------ */
const COMPANIES = [
  { id: 'voltaris', label: 'VOLTARISOS', color: '#4f8fe0', agents: ['production_monitor', 'sales', 'deals'] },
  { id: 'daioakes', label: 'DAI OAKES', color: '#e0793c', agents: ['backoffice'] },
  { id: 'nucleo', label: 'NÚCLEO', color: '#8fc48a', agents: ['market_intelligence', 'marketing', 'operations', 'customer'] },
  { id: 'investigacoes', label: 'INVESTIGAÇÕES', color: '#c98fd8', agents: ['volt', 'dev_debug', 'database', 'finance'] },
];

// Mesma paleta de estados do resto do dashboard (AgentGrid / CoreHero).
const STATE_COLOR = { working: '#f0b429', error: '#d9614f', idle: '#7d7062' };
const STATE_LABEL = { working: 'A TRABALHAR', error: 'ERRO', idle: 'EM ESPERA' };

const VIEW_W = 1000;
const VIEW_H = 640;
const CX = VIEW_W / 2;
const CY = VIEW_H / 2;
const R_INNER = 152;
const R_OUTER = 272;
const R_NODE = 212;
const SECTOR_GAP = 0.1; // radianos de folga entre empresas

function polar(r, a) {
  return [CX + r * Math.cos(a), CY + r * Math.sin(a)];
}

// Sector em anel (fatia de donut) -- a "área" de cada empresa.
function annularSector(rInner, rOuter, a0, a1) {
  const large = a1 - a0 > Math.PI ? 1 : 0;
  const [x0, y0] = polar(rOuter, a0);
  const [x1, y1] = polar(rOuter, a1);
  const [x2, y2] = polar(rInner, a1);
  const [x3, y3] = polar(rInner, a0);
  return `M${x0},${y0} A${rOuter},${rOuter} 0 ${large} 1 ${x1},${y1} L${x2},${y2} A${rInner},${rInner} 0 ${large} 0 ${x3},${y3} Z`;
}

// Etiquetas longas ("INTELIGÊNCIA DE MERCADO") partidas em duas linhas o mais
// equilibradas possível, para não colidirem com o nó vizinho.
function wrapLabel(label) {
  if (label.length <= 13) return [label];
  const words = label.split(' ');
  if (words.length === 1) return [label];
  let cut = 1;
  let best = Infinity;
  for (let i = 1; i < words.length; i++) {
    const diff = Math.abs(words.slice(0, i).join(' ').length - words.slice(i).join(' ').length);
    if (diff < best) {
      best = diff;
      cut = i;
    }
  }
  return [words.slice(0, cut).join(' '), words.slice(cut).join(' ')];
}

function anchorFor(angle) {
  const c = Math.cos(angle);
  if (Math.abs(c) < 0.3) return 'middle';
  return c > 0 ? 'start' : 'end';
}

function TopologyView({ agents }) {
  const [selectedId, setSelectedId] = useState(null);

  const groups = useMemo(() => {
    const byId = Object.fromEntries((agents || []).map(a => [a.id, a]));
    const present = COMPANIES
      .map(company => ({ ...company, members: company.agents.map(id => byId[id]).filter(Boolean) }))
      .filter(company => company.members.length > 0);

    // O sector cresce com o número de agentes, mas com um mínimo fixo por
    // empresa -- senão uma empresa de um só agente (Dai Oakes) ficava com uma
    // fatia ilegível ao lado de uma de quatro.
    const weight = company => company.members.length + 1.2;
    const total = present.reduce((n, company) => n + weight(company), 0) || 1;
    let cursor = -Math.PI / 2;

    return present.map(company => {
      const span = (Math.PI * 2 * weight(company)) / total;
      const a0 = cursor + SECTOR_GAP / 2;
      const a1 = cursor + span - SECTOR_GAP / 2;
      cursor += span;
      const mid = (a0 + a1) / 2;

      const nodes = company.members.map((agent, i) => {
        const angle = a0 + (a1 - a0) * ((i + 0.5) / company.members.length);
        const [x, y] = polar(R_NODE, angle);
        return { agent, angle, x, y };
      });

      const [labelX, labelY] = polar(R_OUTER + 24, mid);
      return { ...company, mid, nodes, labelX, labelY, path: annularSector(R_INNER, R_OUTER, a0, a1) };
    });
  }, [agents]);

  const counts = (agents || []).reduce((acc, agent) => {
    const state = STATE_COLOR[agent.state] ? agent.state : 'idle';
    acc[state] = (acc[state] || 0) + 1;
    return acc;
  }, {});

  const selected = (agents || []).find(agent => agent.id === selectedId) || null;
  const selectedCompany = COMPANIES.find(company => company.agents.includes(selectedId));

  return (
    <div style={{ display: 'flex', gap: 14, alignItems: 'stretch', minHeight: 0 }}>
      {/* ---------------------------------------------------------------- mapa */}
      <div className="panel" style={{ flex: 1, padding: 16, position: 'relative', minWidth: 0 }}>
        <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
          <div className="panel-title">MAPA DE TOPOLOGIA</div>
          <div className="mono" style={{ fontSize: 10, color: '#a89680' }}>
            {(agents || []).length} AGENTES · {groups.length} EMPRESAS
          </div>
        </div>

        <svg viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} preserveAspectRatio="xMidYMid meet" style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }}>
          <defs>
            <filter id="topo-glow" x="-200%" y="-200%" width="500%" height="500%">
              <feGaussianBlur stdDeviation="2.6" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            <radialGradient id="topo-core-glow">
              <stop offset="0%" stopColor="#f0b429" stopOpacity="0.20" />
              <stop offset="100%" stopColor="#f0b429" stopOpacity="0" />
            </radialGradient>
          </defs>

          <circle cx={CX} cy={CY} r={R_OUTER} fill="url(#topo-core-glow)" />

          {/* Território de cada empresa */}
          {groups.map(group => (
            <path
              key={`sector-${group.id}`}
              d={group.path}
              fill={group.color}
              fillOpacity="0.05"
              stroke={group.color}
              strokeOpacity="0.28"
              strokeWidth="1"
            />
          ))}

          {/* Ligações núcleo -> agente, na cor da empresa */}
          {groups.map(group =>
            group.nodes.map(node => {
              const working = node.agent.state === 'working';
              const [x1, y1] = polar(46, node.angle);
              return (
                <line
                  key={`spoke-${node.agent.id}`}
                  x1={x1}
                  y1={y1}
                  x2={node.x}
                  y2={node.y}
                  stroke={group.color}
                  strokeOpacity={working ? 0.65 : 0.22}
                  strokeWidth={working ? 1.6 : 1}
                  strokeDasharray="2 6"
                />
              );
            })
          )}

          {/* Núcleo */}
          <g>
            <circle cx={CX} cy={CY} r="42" fill="rgba(240,180,60,0.08)" stroke="#f0b429" strokeWidth="1.4" />
            <circle cx={CX} cy={CY} r="54" fill="none" stroke="#f0b429" strokeOpacity="0.35" strokeWidth="1" strokeDasharray="4 7">
              <animateTransform attributeName="transform" type="rotate" from={`0 ${CX} ${CY}`} to={`360 ${CX} ${CY}`} dur="48s" repeatCount="indefinite" />
            </circle>
            <g transform={`translate(${CX - 17}, ${CY - 16}) scale(0.31)`}>
              <VoltMark id="topology-hub" />
            </g>
            <text x={CX} y={CY + 78} textAnchor="middle" className="display" fill="#f0b429" style={{ fontSize: 15, letterSpacing: 1.5 }}>
              VOLT CORE
            </text>
          </g>

          {/* Nome da empresa, por fora do seu sector */}
          {groups.map(group => (
            <text
              key={`label-${group.id}`}
              x={group.labelX}
              y={group.labelY}
              textAnchor={anchorFor(group.mid)}
              className="mono"
              fill={group.color}
              style={{ fontSize: 12, fontWeight: 700, letterSpacing: 1.2 }}
            >
              {group.label}
            </text>
          ))}

          {/* Agentes */}
          {groups.map(group =>
            group.nodes.map(node => {
              const agent = node.agent;
              const state = STATE_COLOR[agent.state] ? agent.state : 'idle';
              const stateColor = STATE_COLOR[state];
              const isSelected = agent.id === selectedId;
              const lines = wrapLabel(agent.label);
              const outward = Math.sin(node.angle) >= 0 ? 1 : -1;
              const labelY = node.y + (outward > 0 ? 26 : -20);

              return (
                <g
                  key={`node-${agent.id}`}
                  onClick={() => setSelectedId(isSelected ? null : agent.id)}
                  style={{ cursor: 'pointer' }}
                >
                  {/* área de clique generosa */}
                  <circle cx={node.x} cy={node.y} r="26" fill="transparent" />

                  {state === 'working' && (
                    <circle cx={node.x} cy={node.y} r="11" fill="none" stroke={stateColor} strokeWidth="1.4">
                      <animate attributeName="r" values="11;19;11" dur="2.4s" repeatCount="indefinite" />
                      <animate attributeName="opacity" values="0.8;0;0.8" dur="2.4s" repeatCount="indefinite" />
                    </circle>
                  )}

                  <circle cx={node.x} cy={node.y} r="11" fill="#120e0a" stroke={group.color} strokeWidth={isSelected ? 3 : 1.8} />
                  <circle cx={node.x} cy={node.y} r="4.4" fill={stateColor} filter={state === 'idle' ? undefined : 'url(#topo-glow)'} />

                  {lines.map((line, li) => (
                    <text
                      key={li}
                      x={node.x}
                      y={labelY + li * 11}
                      textAnchor="middle"
                      className="mono"
                      fill={isSelected ? '#f5ead6' : '#a89680'}
                      style={{ fontSize: 9, letterSpacing: 0.4 }}
                    >
                      {line}
                    </text>
                  ))}
                </g>
              );
            })
          )}
        </svg>
      </div>

      {/* ------------------------------------------------------------- legenda */}
      <div style={{ width: 274, display: 'flex', flexDirection: 'column', gap: 12, flexShrink: 0 }}>
        <div className="panel" style={{ padding: 14 }}>
          <div className="panel-title" style={{ marginBottom: 10 }}>ESTADO GERAL</div>
          {['working', 'error', 'idle'].map(state => (
            <div key={state} className="row" style={{ justifyContent: 'space-between', marginBottom: 6 }}>
              <div className="row" style={{ gap: 8 }}>
                <span style={{ width: 9, height: 9, borderRadius: '50%', background: STATE_COLOR[state], display: 'inline-block' }} />
                <span className="mono" style={{ fontSize: 10, color: '#a89680' }}>{STATE_LABEL[state]}</span>
              </div>
              <span className="mono" style={{ fontSize: 11, color: '#f5ead6' }}>{counts[state] || 0}</span>
            </div>
          ))}
        </div>

        <div className="panel" style={{ padding: 14, flex: 1, overflowY: 'auto', minHeight: 0 }}>
          <div className="panel-title" style={{ marginBottom: 10 }}>POR EMPRESA</div>
          {groups.map(group => (
            <div key={group.id} style={{ marginBottom: 14 }}>
              <div className="row" style={{ gap: 7, marginBottom: 7 }}>
                <span style={{ width: 3, height: 12, background: group.color, borderRadius: 2, display: 'inline-block' }} />
                <span className="mono" style={{ fontSize: 10, fontWeight: 700, color: group.color, letterSpacing: 0.8 }}>{group.label}</span>
                <span className="mono" style={{ fontSize: 9, color: '#8a7c68', marginLeft: 'auto' }}>{group.members.length}</span>
              </div>
              <div style={{ display: 'grid', gap: 5 }}>
                {group.members.map(agent => {
                  const state = STATE_COLOR[agent.state] ? agent.state : 'idle';
                  const isSelected = agent.id === selectedId;
                  return (
                    <button
                      type="button"
                      key={agent.id}
                      onClick={() => setSelectedId(isSelected ? null : agent.id)}
                      style={{
                        textAlign: 'left',
                        padding: '6px 8px',
                        borderRadius: 5,
                        border: `1px solid ${isSelected ? group.color : 'transparent'}`,
                        borderLeft: `3px solid ${group.color}`,
                        background: isSelected ? 'rgba(255,255,255,0.06)' : 'rgba(255,255,255,0.025)',
                        color: 'inherit',
                        cursor: 'pointer',
                        width: '100%',
                      }}
                    >
                      <div className="row" style={{ justifyContent: 'space-between', gap: 6 }}>
                        <span style={{ fontSize: 10.5, fontWeight: 600 }}>{agent.label}</span>
                        <span style={{ width: 7, height: 7, borderRadius: '50%', background: STATE_COLOR[state], flexShrink: 0, marginTop: 4 }} />
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        {selected && (
          <div className="panel" style={{ padding: 14 }}>
            <div className="panel-title" style={{ marginBottom: 8 }}>{selected.label}</div>
            {selectedCompany && (
              <div className="mono" style={{ fontSize: 9.5, color: selectedCompany.color, marginBottom: 6, letterSpacing: 0.8 }}>
                {selectedCompany.label}
              </div>
            )}
            <div className="mono" style={{ fontSize: 10, color: STATE_COLOR[STATE_COLOR[selected.state] ? selected.state : 'idle'], marginBottom: 8 }}>
              {STATE_LABEL[STATE_COLOR[selected.state] ? selected.state : 'idle']}
            </div>
            <div style={{ fontSize: 11, color: '#a89680', lineHeight: 1.5 }}>
              {selected.lastActivityText || 'Sem histórico ainda.'}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default TopologyView;
