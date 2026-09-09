import React, { useEffect } from 'react';
import { AGENT_SPEC } from './AgentSheet.jsx';

/* ---------------------------------------------------------------------------
 * Drill-down por cluster: ferramentas em cima -> agente ao centro -> tarefas
 * em baixo, para cada agente do cluster clicado (uma empresa, ou o núcleo
 * reativo ao centro do Mapa de Topologia).
 *
 * Tudo o que aparece aqui vem de AGENT_SPEC (AgentSheet.jsx), que por sua vez
 * foi derivado dos imports e dos TOOL_SCHEMAS em apps/api/app/agents/*.py --
 * nada é inventado para preencher a árvore. Um agente sem ferramentas
 * externas (ex.: operations) mostra-se com a coluna de cima vazia, não com
 * uma ferramenta inventada.
 * ------------------------------------------------------------------------ */

const STATE_COLOR = { working: '#f0b429', error: '#d9614f', idle: '#7d7062' };
const STATE_LABEL = { working: 'A TRABALHAR', error: 'ERRO', idle: 'EM ESPERA' };
const OFF_STROKE = '#6f6250';
const OFF_TEXT = '#8a7c68';
const INK = '#f5ede0';
const INK_MUTED = '#a89680';

function normalise(agent) {
  return STATE_COLOR[agent?.state] ? agent.state : 'idle';
}

function Pill({ children, tone, muted }) {
  return (
    <div
      className="mono"
      style={{
        fontSize: 9,
        lineHeight: 1.4,
        padding: '5px 8px',
        borderRadius: 5,
        background: muted ? 'rgba(255,255,255,0.02)' : 'rgba(255,255,255,0.035)',
        border: `1px solid ${muted ? 'rgba(255,255,255,0.05)' : 'rgba(255,255,255,0.08)'}`,
        color: muted ? OFF_TEXT : tone || INK_MUTED,
        width: '100%',
        boxSizing: 'border-box',
        textAlign: 'center',
        whiteSpace: 'normal',
        wordBreak: 'break-word',
      }}
    >
      {children}
    </div>
  );
}

function Connector({ color }) {
  return <div style={{ width: 1, height: 14, margin: '0 auto', borderLeft: `1px dashed ${color}` }} />;
}

function AgentColumn({ agent, spec, color, connected, agentLabels, onOpenSheet }) {
  const state = normalise(agent);
  const dim = connected === false;
  const nodeColor = dim ? OFF_STROKE : color;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 186, flexShrink: 0, opacity: dim ? 0.5 : 1 }}>
      {/* ferramentas */}
      <div className="mono" style={{ fontSize: 8, color: OFF_TEXT, letterSpacing: 0.1 + 'em', marginBottom: 7, textAlign: 'center' }}>
        FERRAMENTAS
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, width: '100%', minHeight: 20 }}>
        {spec.tools.length ? (
          spec.tools.map(tool => (
            <Pill key={tool} muted={dim}>{tool}</Pill>
          ))
        ) : (
          <Pill muted>SEM FERRAMENTA EXTERNA</Pill>
        )}
      </div>

      <Connector color={dim ? 'rgba(255,255,255,0.12)' : `${color}55`} />

      {/* agente */}
      <button
        type="button"
        onClick={() => onOpenSheet(agent.id)}
        title="Ver ficha completa"
        style={{
          all: 'unset', cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center',
          padding: '9px 12px', borderRadius: 9, border: `1.5px solid ${nodeColor}`,
          background: dim ? 'rgba(255,255,255,0.02)' : 'rgba(255,255,255,0.035)', width: '100%', boxSizing: 'border-box',
        }}
      >
        <div className="row" style={{ gap: 6, alignItems: 'center', marginBottom: 2, justifyContent: 'center' }}>
          {connected !== false && (
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: STATE_COLOR[state], flexShrink: 0 }} />
          )}
          <span style={{ fontSize: 11, fontWeight: 600, color: dim ? OFF_TEXT : INK, textAlign: 'center' }}>{agent.label}</span>
        </div>
        {connected === false ? (
          <span className="mono" style={{ fontSize: 7.5, color: OFF_TEXT, letterSpacing: 0.5 }}>POR LIGAR</span>
        ) : (
          <span className="mono" style={{ fontSize: 7.5, color: STATE_COLOR[state], letterSpacing: 0.5 }}>{STATE_LABEL[state]}</span>
        )}
      </button>

      <Connector color={dim ? 'rgba(255,255,255,0.12)' : `${color}55`} />

      {/* tarefas */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, width: '100%', minHeight: 20 }}>
        {spec.tasks.map(task => (
          <Pill key={task} tone={dim ? undefined : color} muted={dim}>{task}</Pill>
        ))}
      </div>
      <div className="mono" style={{ fontSize: 8, color: OFF_TEXT, letterSpacing: 0.1 + 'em', marginTop: 7, textAlign: 'center' }}>
        TAREFAS
      </div>

      {spec.sends && !dim && (
        <div className="mono" style={{ fontSize: 8, color: OFF_TEXT, marginTop: 8, lineHeight: 1.5, textAlign: 'center' }}>
          despacha para{' '}
          <span style={{ color: '#f0b429' }}>{spec.sends.map(id => agentLabels[id] || id).join(' e ')}</span>
        </div>
      )}
    </div>
  );
}

function ClusterDrilldown({ cluster, agents, agentLabels, onClose, onOpenSheet }) {
  const [showAll, setShowAll] = React.useState(false);

  useEffect(() => {
    setShowAll(false); // cada cluster novo volta a abrir só com os ligados
  }, [cluster && cluster.id]);

  useEffect(() => {
    if (!cluster) return undefined;
    const onKeyDown = e => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [cluster, onClose]);

  if (!cluster) return null;

  const roster = agents || [];
  const hasToggle = cluster.agentIds.length > 1 && !!cluster.connectedIds && cluster.connectedIds.length < cluster.agentIds.length;
  const idsToShow = hasToggle && !showAll ? cluster.connectedIds : cluster.agentIds;
  const columns = idsToShow
    .map(id => ({ agent: roster.find(a => a.id === id), spec: AGENT_SPEC[id] }))
    .filter(c => c.agent && c.spec);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel" style={{ maxWidth: 'min(1180px, 96vw)', width: '100%' }} onClick={e => e.stopPropagation()}>
        <div className="row" style={{ justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4 }}>
          <div>
            <div className="modal-title" style={{ color: cluster.color, marginBottom: 3 }}>{cluster.label}</div>
            <div className="mono" style={{ fontSize: 9.5, color: INK_MUTED }}>
              FERRAMENTAS → AGENTE → TAREFAS · {columns.length} AGENTE{columns.length === 1 ? '' : 'S'}
              {hasToggle && !showAll ? ' · LIGADOS' : ''}
            </div>
          </div>
          <div className="row" style={{ gap: 10, alignItems: 'flex-start' }}>
            {hasToggle && (
              <button
                type="button"
                className="mono"
                onClick={() => setShowAll(v => !v)}
                style={{
                  padding: '5px 9px', borderRadius: 5, border: `1px solid ${cluster.color}44`, background: 'none',
                  color: cluster.color, fontSize: 9, letterSpacing: 0.06 + 'em', cursor: 'pointer', whiteSpace: 'nowrap',
                }}
              >
                {showAll ? `SÓ LIGADOS (${cluster.connectedIds.length})` : `TODOS OS ${cluster.agentIds.length}`}
              </button>
            )}
            <button type="button" className="modal-close" onClick={onClose} aria-label="Fechar">×</button>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 22, overflowX: 'auto', paddingTop: 20, paddingBottom: 6 }}>
          {columns.map(({ agent, spec }) => (
            <AgentColumn
              key={agent.id}
              agent={agent}
              spec={spec}
              color={cluster.color}
              connected={cluster.connectedIds ? cluster.connectedIds.includes(agent.id) : undefined}
              agentLabels={agentLabels}
              onOpenSheet={onOpenSheet}
            />
          ))}
        </div>

        <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid rgba(240,180,60,0.10)', fontSize: 10, color: OFF_TEXT, lineHeight: 1.5 }}>
          Ferramentas e tarefas derivadas do backend — TOOL_SCHEMAS e imports em apps/api/app/agents/*.py, não escritas à mão. Clica num agente para abrir a ficha completa.
        </div>
      </div>
    </div>
  );
}

export default ClusterDrilldown;
