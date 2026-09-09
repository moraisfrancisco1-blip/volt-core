import React, { useMemo, useState } from 'react';
import VoltMark from '../VoltMark.jsx';

/* ---------------------------------------------------------------------------
 * Mapa de topologia -- o Volt Core ao centro e, de cada lado, uma empresa com o
 * roster COMPLETO de agentes à sua volta.
 *
 * O modelo é partilhado, não particionado: os mesmos agentes servem as duas
 * empresas. O que muda por empresa é quais já estão de facto ligados.
 *
 * `connected` = agentes que hoje falam mesmo com o serviço dessa empresa,
 * verificado nos imports de apps/api/app/agents/*.py:
 *   VoltarisOS -> production_monitor (voltaris_tools), market_intelligence,
 *                 sales, deals (voltaris_client)
 *   Dai Oakes  -> backoffice (daioakes_client)
 * Os restantes desenham-se esbatidos como POR LIGAR -- a arquitetura alvo fica
 * visível sem inventar estado que a API não devolve.
 *
 * Porque é que isto está aqui e não vem da API: /api/agents/status devolve UM
 * estado por agente, global, sem dimensão de empresa. Quando o backend passar a
 * dar estado por sistema (o dashboard já recebe `systems`, e repo_config /
 * railway_config já são indexados por system), esta constante desaparece e o
 * mapa passa a ser inteiramente data-driven.
 * ------------------------------------------------------------------------ */
const COMPANIES = [
  { id: 'voltaris', label: 'VOLTARISOS', color: '#4f8fe0', connected: ['production_monitor', 'market_intelligence', 'sales', 'deals'] },
  { id: 'daioakes', label: 'DAI OAKES', color: '#e0793c', connected: ['backoffice'] },
];

// Mesma paleta de estados do resto do dashboard (AgentGrid / CoreHero).
const STATE_COLOR = { working: '#f0b429', error: '#d9614f', idle: '#7d7062' };
const STATE_LABEL = { working: 'A TRABALHAR', error: 'ERRO', idle: 'EM ESPERA' };
const OFF_STROKE = '#6f6250';
const OFF_TEXT = '#8a7c68';

const VIEW_W = 1240;
const VIEW_H = 560;
const CY = 268;
const CORE_X = VIEW_W / 2;
const CORE_R = 42;
const HUB_R = 27;
const RING_R = 152;
const NODE_R = 9;
const CLUSTER_DX = 330; // distância do núcleo a cada hub de empresa
// Os agentes ocupam 300° e não 360°: a abertura fica virada ao núcleo, para a
// ligação empresa->Volt Core passar por espaço vazio em vez de cortar nós.
const ARC_SPAN = (300 * Math.PI) / 180;

function polar(cx, cy, r, a) {
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}

// Etiquetas longas ("INTELIGÊNCIA DE MERCADO") partidas em duas linhas o mais
// equilibradas possível, para não colidirem com o nó vizinho.
function wrapLabel(label) {
  if (label.length <= 12) return [label];
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

function normalise(agent) {
  return STATE_COLOR[agent.state] ? agent.state : 'idle';
}

function TopologyView({ agents }) {
  const [selected, setSelected] = useState(null); // { agentId, companyId }

  const roster = agents || [];

  const clusters = useMemo(() => {
    if (!roster.length) return [];

    return COMPANIES.map((company, ci) => {
      const hubX = CORE_X + (ci === 0 ? -CLUSTER_DX : CLUSTER_DX);
      const away = ci === 0 ? Math.PI : 0; // arco virado para fora, longe do núcleo
      const nodes = roster.map((agent, i) => {
        const angle = away - ARC_SPAN / 2 + (ARC_SPAN * (i + 0.5)) / roster.length;
        const [x, y] = polar(hubX, CY, RING_R, angle);

        // Nos nós laterais uma etiqueta centrada por cima do raio cai em cima do
        // próprio nó (é larga e está a 26px dele), por isso encosta-se ao lado.
        const cos = Math.cos(angle);
        let lx;
        let ly;
        let anchor;
        if (Math.abs(cos) > 0.5) {
          anchor = cos > 0 ? 'start' : 'end';
          lx = x + (cos > 0 ? NODE_R + 7 : -(NODE_R + 7));
          ly = y - 3;
        } else {
          anchor = 'middle';
          [lx, ly] = polar(hubX, CY, RING_R + 26, angle);
        }
        return { agent, angle, x, y, lx, ly, anchor, connected: company.connected.includes(agent.id) };
      });
      const connectedCount = nodes.filter(n => n.connected).length;
      return { ...company, hubX, nodes, connectedCount };
    });
  }, [roster]);

  const detail = useMemo(() => {
    if (!selected) return null;
    const agent = roster.find(a => a.id === selected.agentId);
    const company = COMPANIES.find(c => c.id === selected.companyId);
    if (!agent || !company) return null;
    return { agent, company, connected: company.connected.includes(agent.id) };
  }, [selected, roster]);

  return (
    <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start', minHeight: 0 }}>
      {/* ---------------------------------------------------------------- mapa */}
      <div className="panel" style={{ flex: 1, padding: 16, minWidth: 0 }}>
        <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
          <div className="panel-title">MAPA DE TOPOLOGIA</div>
          <div className="mono" style={{ fontSize: 10, color: '#a89680' }}>
            {roster.length} AGENTES POR EMPRESA · {COMPANIES.length} EMPRESAS
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
              <stop offset="0%" stopColor="#f0b429" stopOpacity="0.22" />
              <stop offset="100%" stopColor="#f0b429" stopOpacity="0" />
            </radialGradient>
          </defs>

          <circle cx={CORE_X} cy={CY} r={150} fill="url(#topo-core-glow)" />

          {clusters.map(cluster => (
            <g key={cluster.id}>
              {/* território da empresa */}
              <circle cx={cluster.hubX} cy={CY} r={RING_R} fill={cluster.color} fillOpacity="0.035" stroke={cluster.color} strokeOpacity="0.2" strokeWidth="1" strokeDasharray="3 8" />

              {/* núcleo -> hub da empresa */}
              <line
                x1={CORE_X + (cluster.hubX < CORE_X ? -CORE_R : CORE_R)}
                y1={CY}
                x2={cluster.hubX + (cluster.hubX < CORE_X ? HUB_R : -HUB_R)}
                y2={CY}
                stroke={cluster.color}
                strokeOpacity="0.55"
                strokeWidth="1.6"
              />

              {/* hub -> agente */}
              {cluster.nodes.map(node => (
                <line
                  key={`spoke-${cluster.id}-${node.agent.id}`}
                  x1={cluster.hubX}
                  y1={CY}
                  x2={node.x}
                  y2={node.y}
                  stroke={node.connected ? cluster.color : OFF_STROKE}
                  strokeOpacity={node.connected ? (node.agent.state === 'working' ? 0.6 : 0.3) : 0.5}
                  strokeWidth={node.connected && node.agent.state === 'working' ? 1.5 : 1}
                  strokeDasharray={node.connected ? '2 5' : '1 6'}
                />
              ))}

              {/* hub da empresa */}
              <circle cx={cluster.hubX} cy={CY} r={HUB_R} fill="#120e0a" stroke={cluster.color} strokeWidth="1.6" />
              <text x={cluster.hubX} y={CY + 3} textAnchor="middle" className="mono" fill={cluster.color} style={{ fontSize: 11, fontWeight: 700 }}>
                {cluster.connectedCount}/{roster.length}
              </text>
              <text x={cluster.hubX} y={CY - HUB_R - 14} textAnchor="middle" className="display" fill={cluster.color} style={{ fontSize: 14, letterSpacing: 1.4 }}>
                {cluster.label}
              </text>
              <text x={cluster.hubX} y={CY + HUB_R + 20} textAnchor="middle" className="mono" fill="#8a7c68" style={{ fontSize: 8.5, letterSpacing: 0.6 }}>
                LIGADOS
              </text>

              {/* agentes */}
              {cluster.nodes.map(node => {
                const state = normalise(node.agent);
                const isSelected = selected && selected.agentId === node.agent.id && selected.companyId === cluster.id;
                const lines = wrapLabel(node.agent.label);

                return (
                  <g
                    key={`node-${cluster.id}-${node.agent.id}`}
                    onClick={() => setSelected(isSelected ? null : { agentId: node.agent.id, companyId: cluster.id })}
                    style={{ cursor: 'pointer' }}
                  >
                    <circle cx={node.x} cy={node.y} r="22" fill="transparent" />

                    {node.connected && state === 'working' && (
                      <circle cx={node.x} cy={node.y} r={NODE_R} fill="none" stroke={STATE_COLOR.working} strokeWidth="1.3">
                        <animate attributeName="r" values={`${NODE_R};${NODE_R + 8};${NODE_R}`} dur="2.4s" repeatCount="indefinite" />
                        <animate attributeName="opacity" values="0.8;0;0.8" dur="2.4s" repeatCount="indefinite" />
                      </circle>
                    )}

                    <circle
                      cx={node.x}
                      cy={node.y}
                      r={NODE_R}
                      fill="#120e0a"
                      stroke={node.connected ? cluster.color : OFF_STROKE}
                      strokeWidth={isSelected ? 2.8 : node.connected ? 1.8 : 1.2}
                    />
                    {node.connected ? (
                      <circle cx={node.x} cy={node.y} r="3.8" fill={STATE_COLOR[state]} filter={state === 'idle' ? undefined : 'url(#topo-glow)'} />
                    ) : (
                      <circle cx={node.x} cy={node.y} r="2.4" fill={OFF_STROKE} fillOpacity="0.7" />
                    )}

                    {lines.map((line, li) => (
                      <text
                        key={li}
                        x={node.lx}
                        y={node.ly + li * 10 + (lines.length > 1 ? 0 : 3)}
                        textAnchor={node.anchor}
                        className="mono"
                        fill={isSelected ? '#f5ead6' : node.connected ? '#a89680' : OFF_TEXT}
                        style={{ fontSize: 8.5, letterSpacing: 0.3 }}
                      >
                        {line}
                      </text>
                    ))}
                  </g>
                );
              })}
            </g>
          ))}

          {/* núcleo */}
          <g>
            <circle cx={CORE_X} cy={CY} r={CORE_R} fill="rgba(240,180,60,0.08)" stroke="#f0b429" strokeWidth="1.4" />
            <circle cx={CORE_X} cy={CY} r={CORE_R + 12} fill="none" stroke="#f0b429" strokeOpacity="0.32" strokeWidth="1" strokeDasharray="4 7">
              <animateTransform attributeName="transform" type="rotate" from={`0 ${CORE_X} ${CY}`} to={`360 ${CORE_X} ${CY}`} dur="48s" repeatCount="indefinite" />
            </circle>
            <g transform={`translate(${CORE_X - 17}, ${CY - 16}) scale(0.31)`}>
              <VoltMark id="topology-hub" />
            </g>
            <text x={CORE_X} y={CY + CORE_R + 28} textAnchor="middle" className="display" fill="#f0b429" style={{ fontSize: 15, letterSpacing: 1.5 }}>
              VOLT CORE
            </text>
          </g>
        </svg>
      </div>

      {/* ------------------------------------------------------------- legenda */}
      <div style={{ width: 274, display: 'flex', flexDirection: 'column', gap: 12, flexShrink: 0, maxHeight: 'calc(100vh - 170px)' }}>
        <div className="panel" style={{ padding: 14 }}>
          <div className="panel-title" style={{ marginBottom: 10 }}>COBERTURA</div>
          {clusters.map(cluster => (
            <div key={cluster.id} style={{ marginBottom: 10 }}>
              <div className="row" style={{ justifyContent: 'space-between', marginBottom: 5 }}>
                <span className="mono" style={{ fontSize: 10, fontWeight: 700, color: cluster.color, letterSpacing: 0.8 }}>{cluster.label}</span>
                <span className="mono" style={{ fontSize: 10, color: '#a89680' }}>{cluster.connectedCount}/{roster.length}</span>
              </div>
              <div style={{ height: 4, borderRadius: 2, background: 'rgba(255,255,255,0.06)', overflow: 'hidden' }}>
                <div style={{ width: `${roster.length ? (cluster.connectedCount / roster.length) * 100 : 0}%`, height: '100%', background: cluster.color }} />
              </div>
            </div>
          ))}
        </div>

        <div className="panel" style={{ padding: 14, flex: 1, overflowY: 'auto', minHeight: 0 }}>
          {clusters.map(cluster => (
            <div key={cluster.id} style={{ marginBottom: 16 }}>
              <div className="row" style={{ gap: 7, marginBottom: 8 }}>
                <span style={{ width: 3, height: 12, background: cluster.color, borderRadius: 2, display: 'inline-block' }} />
                <span className="mono" style={{ fontSize: 10, fontWeight: 700, color: cluster.color, letterSpacing: 0.8 }}>{cluster.label}</span>
              </div>
              <div style={{ display: 'grid', gap: 4 }}>
                {cluster.nodes.map(node => {
                  const state = normalise(node.agent);
                  const isSelected = selected && selected.agentId === node.agent.id && selected.companyId === cluster.id;
                  return (
                    <button
                      type="button"
                      key={`${cluster.id}-${node.agent.id}`}
                      onClick={() => setSelected(isSelected ? null : { agentId: node.agent.id, companyId: cluster.id })}
                      style={{
                        textAlign: 'left',
                        padding: '5px 8px',
                        borderRadius: 5,
                        border: `1px solid ${isSelected ? cluster.color : 'transparent'}`,
                        borderLeft: `3px solid ${node.connected ? cluster.color : OFF_STROKE}`,
                        background: isSelected ? 'rgba(255,255,255,0.06)' : 'rgba(255,255,255,0.022)',
                        color: 'inherit',
                        cursor: 'pointer',
                        width: '100%',
                        opacity: node.connected ? 1 : 0.55,
                      }}
                    >
                      <div className="row" style={{ justifyContent: 'space-between', gap: 6, alignItems: 'center' }}>
                        <span style={{ fontSize: 10, fontWeight: 600 }}>{node.agent.label}</span>
                        {node.connected ? (
                          <span style={{ width: 7, height: 7, borderRadius: '50%', background: STATE_COLOR[state], flexShrink: 0 }} />
                        ) : (
                          <span className="mono" style={{ fontSize: 7.5, color: OFF_TEXT, flexShrink: 0, letterSpacing: 0.5 }}>POR LIGAR</span>
                        )}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        {detail && (
          <div className="panel" style={{ padding: 14 }}>
            <div className="panel-title" style={{ marginBottom: 6 }}>{detail.agent.label}</div>
            <div className="mono" style={{ fontSize: 9.5, color: detail.company.color, marginBottom: 6, letterSpacing: 0.8 }}>
              {detail.company.label}
            </div>
            {detail.connected ? (
              <>
                <div className="mono" style={{ fontSize: 10, color: STATE_COLOR[normalise(detail.agent)], marginBottom: 8 }}>
                  {STATE_LABEL[normalise(detail.agent)]}
                </div>
                <div style={{ fontSize: 11, color: '#a89680', lineHeight: 1.5 }}>
                  {detail.agent.lastActivityText || 'Sem histórico ainda.'}
                </div>
              </>
            ) : (
              <div style={{ fontSize: 11, color: OFF_TEXT, lineHeight: 1.5 }}>
                Ainda não ligado a esta empresa. Falta o endpoint do lado da {detail.company.label} para este agente.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default TopologyView;
