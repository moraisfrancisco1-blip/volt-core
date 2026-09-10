import React, { useMemo, useState } from 'react';
import VoltMark from '../VoltMark.jsx';
import AgentSheet from '../AgentSheet.jsx';
import { AGENT_SPEC } from '../AgentSheet.jsx';

/* ---------------------------------------------------------------------------
 * Organograma -- a mesma frota de agentes que o Mapa de Topologia, mas lida
 * por AUTORIDADE em vez de por empresa: quem decide o quê, e onde é que tu
 * entras na cadeia.
 *
 * Não repete o Mapa de Topologia por acaso -- lá a pergunta é "a que sistema
 * está ligado este agente"; aqui é "quem aprova o que este agente faz". As
 * três colunas são as mesmas três escadas de AgentSheet.jsx (RUNGS), lidas
 * como três estilos de gestão em vez de três estados isolados.
 *
 * `COMPANY_OF` espelha de propósito o `COMPANIES.connected` do
 * TopologyView.jsx -- é a mesma informação (imports em
 * apps/api/app/agents/*.py), só que aqui cada agente aparece uma vez, não
 * duas. Se um agente mudar de empresa lá, muda aqui também.
 * ------------------------------------------------------------------------ */

const COMPANY_OF = {
  production_monitor: 'voltaris',
  market_intelligence: 'voltaris',
  sales: 'voltaris',
  deals: 'voltaris',
  backoffice: 'daioakes',
};
const COMPANY_META = {
  voltaris: { label: 'VOLTARISOS', color: '#4f8fe0' },
  daioakes: { label: 'DAI OAKES', color: '#e0793c' },
};

// Só estes quatro fazem parte da cadeia reativa central (ver runner.py /
// finance_runner.py) -- "NÚCLEO" é o rótulo deles, não um valor por omissão.
// Um agente de "propõe" sem empresa (marketing, operations, customer) ainda
// não está ligado a nenhuma -- mesma leitura do "POR LIGAR" do Mapa de
// Topologia, não é núcleo nenhum.
const NUCLEO_IDS = new Set(['volt', 'dev_debug', 'database', 'finance']);

const COLUMNS = [
  { rung: 'reactive', label: 'REATIVO', color: '#9a8a72', blurb: 'Só corre quando um evento o dispara. Ninguém aprova -- o gatilho já é a decisão.' },
  { rung: 'proposes', label: 'PROPÕE · TU APROVAS', color: '#f0b429', blurb: 'Prepara o trabalho e para. Só sai depois de carregares em Aprovar.' },
  { rung: 'autonomous', label: 'AUTÓNOMO', color: '#8fc48a', blurb: 'Corre sozinho em intervalo e grava o resultado. Não passa por ti.' },
];

const INK = '#f5ede0';
const INK_MUTED = '#a89680';
const OFF_TEXT = '#8a7c68';

function Stem({ h = 20, color = 'rgba(240,180,60,0.35)' }) {
  return <div style={{ width: 1, height: h, margin: '0 auto', background: color }} />;
}

function AgentChip({ agentId, agentLabels, roster, color, onOpen }) {
  const agent = roster.find(a => a.id === agentId);
  const spec = AGENT_SPEC[agentId];
  if (!agent || !spec) return null;
  const companyId = COMPANY_OF[agentId];
  const company = companyId ? COMPANY_META[companyId] : null;
  const stateColor = { working: '#f0b429', error: '#d9614f', idle: OFF_TEXT }[agent.state] || OFF_TEXT;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: '100%' }}>
      <button
        type="button"
        onClick={() => onOpen(agent.id)}
        style={{
          all: 'unset', cursor: 'pointer', width: '100%', boxSizing: 'border-box',
          padding: '8px 10px', borderRadius: 8, border: `1px solid ${color}55`,
          background: 'rgba(255,255,255,0.03)', textAlign: 'center',
        }}
      >
        <div className="row" style={{ justifyContent: 'center', gap: 6, marginBottom: 2 }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: stateColor, flexShrink: 0 }} />
          <span style={{ fontSize: 11.5, fontWeight: 600, color: INK }}>{agent.label}</span>
        </div>
        {company ? (
          <span className="mono" style={{ fontSize: 8, color: company.color, letterSpacing: 0.06 + 'em' }}>{company.label}</span>
        ) : NUCLEO_IDS.has(agentId) ? (
          <span className="mono" style={{ fontSize: 8, color: OFF_TEXT, letterSpacing: 0.06 + 'em' }}>NÚCLEO</span>
        ) : (
          <span className="mono" style={{ fontSize: 8, color: OFF_TEXT, letterSpacing: 0.06 + 'em' }}>POR LIGAR</span>
        )}
      </button>

      {spec.sends && (
        <div className="mono" style={{ fontSize: 8, color: OFF_TEXT, marginTop: 5, lineHeight: 1.4, textAlign: 'center' }}>
          despacha para <span style={{ color }}>{spec.sends.map(id => agentLabels[id] || id).join(' e ')}</span>
        </div>
      )}
      {spec.gate && (
        <div className="mono" style={{ fontSize: 8, color: '#f0b429', marginTop: 5, lineHeight: 1.4, textAlign: 'center' }}>
          ↑ aprovação sobe a TU
        </div>
      )}
      {spec.rung === 'autonomous' && (
        <div className="mono" style={{ fontSize: 8, color: OFF_TEXT, marginTop: 5, letterSpacing: 0.04 + 'em' }}>
          grava sozinho
        </div>
      )}
    </div>
  );
}

function OrgChartView({ agents, integrations }) {
  const [sheetFor, setSheetFor] = useState(null);
  const roster = agents || [];
  const agentLabels = useMemo(() => Object.fromEntries(roster.map(a => [a.id, a.label])), [roster]);

  const columns = useMemo(() => COLUMNS.map(col => ({
    ...col,
    agentIds: roster.map(a => a.id).filter(id => AGENT_SPEC[id]?.rung === col.rung),
  })), [roster]);

  return (
    <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start', minHeight: 0 }}>
      <div className="panel" style={{ flex: 1, padding: 20, minWidth: 0 }}>
        <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 18 }}>
          <div className="panel-title">ORGANOGRAMA</div>
          <div className="mono" style={{ fontSize: 10, color: INK_MUTED }}>QUEM DECIDE O QUÊ</div>
        </div>

        <div style={{ textAlign: 'center' }}>
          <div style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'center', padding: '9px 20px', borderRadius: 9, border: '1px solid rgba(240,180,60,0.4)', background: 'rgba(240,180,60,0.07)' }}>
            <span className="display" style={{ fontSize: 13, color: '#f0b429', letterSpacing: 1.2 }}>TU</span>
            <span className="mono" style={{ fontSize: 8, color: OFF_TEXT, marginTop: 2 }}>OPERAS O VOLT CORE</span>
          </div>

          <Stem />

          <div style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'center', padding: '10px 24px', borderRadius: 10, border: '1.4px solid #f0b429', background: 'rgba(240,180,60,0.05)' }}>
            <div style={{ width: 26, height: 26, marginBottom: 4 }}>
              <div style={{ transform: 'scale(0.4) translate(-30%, -30%)' }}>
                <VoltMark id="orgchart-hub" />
              </div>
            </div>
            <span className="display" style={{ fontSize: 13, color: '#f0b429', letterSpacing: 1.2 }}>VOLT CORE</span>
            <span className="mono" style={{ fontSize: 8, color: OFF_TEXT, marginTop: 2 }}>{roster.length} AGENTES</span>
          </div>

          <Stem />
          <div style={{ width: '88%', maxWidth: 760, margin: '0 auto', borderTop: '1px dashed rgba(240,180,60,0.3)' }} />

          <div style={{ display: 'flex', justifyContent: 'space-around', gap: 18, marginTop: 0 }}>
            {columns.map(col => (
              <div key={col.rung} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: 0 }}>
                <Stem h={16} color={`${col.color}66`} />
                <div style={{ padding: '6px 14px', borderRadius: 7, border: `1px solid ${col.color}55`, background: `${col.color}14`, marginBottom: 4 }}>
                  <span className="mono" style={{ fontSize: 10, fontWeight: 700, color: col.color, letterSpacing: 0.08 + 'em' }}>{col.label}</span>
                </div>
                <div style={{ fontSize: 9.5, color: OFF_TEXT, lineHeight: 1.4, textAlign: 'center', marginBottom: 14, minHeight: 26 }}>
                  {col.blurb}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 16, width: '100%' }}>
                  {col.agentIds.map(id => (
                    <AgentChip key={id} agentId={id} agentLabels={agentLabels} roster={roster} color={col.color} onOpen={agentId => setSheetFor(agentId)} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div style={{ width: 250, flexShrink: 0 }}>
        <div className="panel" style={{ padding: 14 }}>
          <div className="panel-title" style={{ marginBottom: 8 }}>COMO LER</div>
          <div style={{ fontSize: 11, color: INK_MUTED, lineHeight: 1.6 }}>
            O Mapa de Topologia mostra a que sistema cada agente está ligado. Este organograma mostra outra coisa: onde é que a tua aprovação entra.
          </div>
          <div style={{ marginTop: 12, display: 'grid', gap: 8 }}>
            {COLUMNS.map(col => (
              <div key={col.rung} className="row" style={{ gap: 7, alignItems: 'flex-start' }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: col.color, flexShrink: 0, marginTop: 3 }} />
                <span style={{ fontSize: 10.5, color: INK_MUTED, lineHeight: 1.5 }}>
                  <strong style={{ color: col.color }}>{col.label}</strong> — {col.blurb}
                </span>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid rgba(255,255,255,0.07)', fontSize: 10, color: OFF_TEXT, lineHeight: 1.5 }}>
            Clica num agente para abrir a ficha completa. Degraus derivados do backend — ver AGENT_SPEC em AgentSheet.jsx.
          </div>
        </div>
      </div>

      <AgentSheet
        agent={sheetFor ? roster.find(a => a.id === sheetFor) : null}
        company={sheetFor && COMPANY_OF[sheetFor] ? COMPANY_META[COMPANY_OF[sheetFor]] : null}
        integrations={integrations}
        agentLabels={agentLabels}
        onClose={() => setSheetFor(null)}
      />
    </div>
  );
}

export default OrgChartView;
