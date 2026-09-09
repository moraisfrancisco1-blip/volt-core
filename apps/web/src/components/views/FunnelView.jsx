import React, { useMemo, useState } from 'react';

/* ---------------------------------------------------------------------------
 * Funil de vendas -- as etapas reais que o backend produz, nada inventado.
 *
 * O pipeline de deals é EXCLUSIVAMENTE B2B: em deals_agent._sync_deals_from_leads()
 * só entram leads com lead_type == 'b2b_partner' E que já tenham um rascunho de
 * outreach com status 'approved_sent'. Os tenants reais da VoltarisOS nunca são
 * corridos pelo pipeline de fecho (está escrito lá: "never run through the
 * deal-closing pipeline"), por isso aparecem numa pista à parte em vez de
 * inflarem o funil.
 *
 * Contagem cumulativa: "chegou à etapa X" = está em X ou mais à frente. Um deal
 * closed_lost conta como negócio aberto (chegou lá) mas não entra nas etapas
 * seguintes -- o registo não diz em que ponto caiu, por isso vai para um cartão
 * próprio em vez de ser distribuído por adivinhação.
 * ------------------------------------------------------------------------ */

// Ramp ordinal de um só tom (validada: L monótona, gaps >= 0.06, extremo claro
// acima da superfície #16110c). Etapas ordenadas -> ramp ordinal, não paleta
// categórica. A última etapa usa o verde de estado porque É um estado.
const RAMP = ['#f9d179', '#f0b429', '#d29722', '#b8811d', '#9a6b19', '#7d5615'];
const GOOD = '#8fc48a';
const BAD = '#d9614f';
const INK = '#f5ede0';
const INK_MUTED = '#a89680';
const INK_FAINT = '#8a7c68';
const HAIRLINE = 'rgba(240,180,60,0.10)';

const REACHED_PROPOSAL = ['proposal_prepared', 'negotiating', 'closed_won'];
const REACHED_NEGOTIATING = ['negotiating', 'closed_won'];

function pct(part, whole) {
  if (!whole) return null;
  return (part / whole) * 100;
}

function fmtPct(value) {
  if (value == null) return '—';
  return `${value >= 10 || value === 0 ? Math.round(value) : value.toFixed(1)}%`;
}

function FunnelView({ leads, drafts, deals }) {
  const [hovered, setHovered] = useState(null);
  const [showTable, setShowTable] = useState(false);

  const model = useMemo(() => {
    const allLeads = leads || [];
    const allDrafts = drafts || [];
    const allDeals = deals || [];

    // leads que já receberam outreach mesmo enviado
    const contactedLeadIds = new Set(
      allDrafts.filter(d => d.status === 'approved_sent' && d.lead_id != null).map(d => d.lead_id)
    );

    const b2b = allLeads.filter(l => l.lead_type === 'b2b_partner');
    const b2bQualified = b2b.filter(l => l.status === 'qualified');
    const b2bContacted = b2bQualified.filter(l => contactedLeadIds.has(l.id));

    const stages = [
      { id: 'leads', label: 'LEADS B2B', count: b2b.length, color: RAMP[0], note: 'Parceiros B2B no registo.' },
      { id: 'qualified', label: 'QUALIFICADOS', count: b2bQualified.length, color: RAMP[1], note: 'O agente Sales marcou como qualificado.' },
      { id: 'contacted', label: 'CONTACTADOS', count: b2bContacted.length, color: RAMP[2], note: 'Outreach aprovado e enviado.' },
      { id: 'deal', label: 'NEGÓCIO ABERTO', count: allDeals.length, color: RAMP[3], note: 'Entrou no pipeline de deals (inclui os que se vieram a perder).' },
      { id: 'proposal', label: 'PROPOSTA', count: allDeals.filter(d => REACHED_PROPOSAL.includes(d.stage)).length, color: RAMP[4], note: 'Chegou a proposta preparada ou mais à frente.' },
      { id: 'negotiating', label: 'NEGOCIAÇÃO', count: allDeals.filter(d => REACHED_NEGOTIATING.includes(d.stage)).length, color: RAMP[5], note: 'Chegou a negociação ou fechou ganho.' },
      { id: 'won', label: 'FECHADO GANHO', count: allDeals.filter(d => d.stage === 'closed_won').length, color: GOOD, note: 'Fechado ganho.' },
    ];

    const top = stages[0].count;
    stages.forEach((stage, i) => {
      stage.share = pct(stage.count, top);
      stage.step = i === 0 ? null : pct(stage.count, stages[i - 1].count);
    });

    const lost = allDeals.filter(d => d.stage === 'closed_lost').length;

    // Pista dos tenants -- motion diferente, nunca entra no funil acima.
    const tenants = allLeads.filter(l => l.lead_type === 'tenant_signup');
    const tenantTrack = [
      { label: 'TENANTS REAIS', count: tenants.length },
      { label: 'PROCESSADOS', count: tenants.filter(l => l.status === 'qualified').length },
      { label: 'BOAS-VINDAS ENVIADAS', count: tenants.filter(l => contactedLeadIds.has(l.id)).length },
    ];

    return { stages, top, lost, tenantTrack, totalDeals: allDeals.length };
  }, [leads, drafts, deals]);

  const { stages, top, lost, tenantTrack } = model;
  const won = stages[stages.length - 1];
  const overall = pct(won.count, top);

  const kpis = [
    { label: 'LEADS B2B', value: top, color: RAMP[1] },
    { label: 'NEGÓCIOS ABERTOS', value: stages[3].count, color: RAMP[3] },
    { label: 'FECHADOS GANHOS', value: won.count, color: GOOD },
    { label: 'CONVERSÃO GLOBAL', value: fmtPct(overall), color: INK },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* ------------------------------------------------------------- KPIs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
        {kpis.map(kpi => (
          <div className="panel" key={kpi.label} style={{ padding: 14 }}>
            <div className="panel-title" style={{ marginBottom: 8 }}>{kpi.label}</div>
            <div style={{ fontSize: 30, fontWeight: 600, color: kpi.color, lineHeight: 1 }}>{kpi.value}</div>
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
        {/* ----------------------------------------------------------- funil */}
        <div className="panel" style={{ flex: 1, padding: 16, minWidth: 0 }}>
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
            <div className="panel-title" style={{ margin: 0 }}>FUNIL B2B</div>
            <button
              type="button"
              className="mono"
              onClick={() => setShowTable(v => !v)}
              style={{ background: 'none', border: `1px solid ${HAIRLINE}`, borderRadius: 6, color: INK_MUTED, fontSize: 9.5, padding: '4px 9px', cursor: 'pointer', letterSpacing: 0.6 }}
            >
              {showTable ? 'VER GRÁFICO' : 'VER TABELA'}
            </button>
          </div>
          <div className="mono" style={{ fontSize: 9.5, color: INK_FAINT, marginBottom: 16, lineHeight: 1.5 }}>
            Contagem cumulativa · só parceiros B2B entram neste pipeline
          </div>

          {top === 0 ? (
            <div className="empty-state">Ainda não há leads B2B no registo.</div>
          ) : showTable ? (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11.5 }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${HAIRLINE}` }}>
                  {['Etapa', 'Nº', '% do topo', '% da anterior'].map((h, i) => (
                    <th key={h} className="mono" style={{ textAlign: i === 0 ? 'left' : 'right', padding: '7px 6px', color: INK_FAINT, fontSize: 9.5, fontWeight: 600, letterSpacing: 0.6 }}>
                      {h.toUpperCase()}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {stages.map(stage => (
                  <tr key={stage.id} style={{ borderBottom: `1px solid ${HAIRLINE}` }}>
                    <td style={{ padding: '7px 6px', color: INK }}>
                      <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: stage.color, marginRight: 8 }} />
                      {stage.label}
                    </td>
                    <td className="mono" style={{ textAlign: 'right', padding: '7px 6px', color: INK, fontVariantNumeric: 'tabular-nums' }}>{stage.count}</td>
                    <td className="mono" style={{ textAlign: 'right', padding: '7px 6px', color: INK_MUTED, fontVariantNumeric: 'tabular-nums' }}>{fmtPct(stage.share)}</td>
                    <td className="mono" style={{ textAlign: 'right', padding: '7px 6px', color: INK_MUTED, fontVariantNumeric: 'tabular-nums' }}>{fmtPct(stage.step)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div>
              {stages.map((stage, i) => {
                const width = top ? Math.max((stage.count / top) * 100, stage.count > 0 ? 1.5 : 0) : 0;
                const isHovered = hovered === stage.id;

                return (
                  <div key={stage.id}>
                    {/* queda entre etapas */}
                    {i > 0 && (
                      <div className="mono" style={{ fontSize: 9, color: INK_FAINT, padding: '3px 0 3px 168px', letterSpacing: 0.4 }}>
                        {fmtPct(stage.step)} seguem
                        {stages[i - 1].count - stage.count > 0 && ` · −${stages[i - 1].count - stage.count}`}
                      </div>
                    )}

                    <div
                      className="row"
                      onMouseEnter={() => setHovered(stage.id)}
                      onMouseLeave={() => setHovered(null)}
                      style={{ gap: 12, alignItems: 'center', position: 'relative', padding: '3px 0', cursor: 'default' }}
                    >
                      <div className="mono" style={{ width: 156, flexShrink: 0, textAlign: 'right', fontSize: 10, color: isHovered ? INK : INK_MUTED, letterSpacing: 0.5 }}>
                        {stage.label}
                      </div>

                      <div style={{ flex: 1, minWidth: 0, position: 'relative', height: 26, display: 'flex', alignItems: 'center', gap: 9 }}>
                        {/* a pista own o 100% -- a barra mede-se contra ela, e o
                            valor fica de fora, para a percentagem não ser comida
                            pelo espaço do número */}
                        <div style={{ flex: 1, minWidth: 0, position: 'relative', height: 26, display: 'flex', alignItems: 'center' }}>
                          <div style={{ position: 'absolute', inset: '5px 0', borderRadius: 4, background: 'rgba(255,255,255,0.025)' }} />
                          <div
                            style={{
                              position: 'relative',
                              height: 16,
                              width: `${width}%`,
                              flexShrink: 0,
                              background: stage.color,
                              borderRadius: '2px 4px 4px 2px',
                              opacity: hovered && !isHovered ? 0.55 : 1,
                              transition: 'opacity 120ms',
                            }}
                          />
                        </div>
                        {/* os passos escuros da ramp não sustentam texto por cima,
                            por isso o valor vive sempre fora da barra */}
                        <span className="mono" style={{ fontSize: 11, color: INK, fontVariantNumeric: 'tabular-nums', flexShrink: 0, minWidth: 22, textAlign: 'right' }}>
                          {stage.count}
                        </span>

                        {isHovered && (
                          <div
                            style={{
                              position: 'absolute',
                              left: 0,
                              top: 30,
                              zIndex: 5,
                              background: '#1b150e',
                              border: `1px solid ${HAIRLINE}`,
                              borderRadius: 7,
                              padding: '9px 11px',
                              boxShadow: '0 10px 26px rgba(0,0,0,0.55)',
                              minWidth: 230,
                              pointerEvents: 'none',
                            }}
                          >
                            <div className="mono" style={{ fontSize: 10, color: stage.color, marginBottom: 5, letterSpacing: 0.6 }}>{stage.label}</div>
                            <div style={{ fontSize: 11, color: INK, marginBottom: 4 }}>
                              {stage.count} · {fmtPct(stage.share)} do topo
                              {stage.step != null && ` · ${fmtPct(stage.step)} da anterior`}
                            </div>
                            <div style={{ fontSize: 10, color: INK_MUTED, lineHeight: 1.45 }}>{stage.note}</div>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* --------------------------------------------------------- lateral */}
        <div style={{ width: 268, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div className="panel" style={{ padding: 14 }}>
            <div className="panel-title" style={{ marginBottom: 8 }}>FECHADOS PERDIDOS</div>
            <div className="row" style={{ gap: 9, alignItems: 'baseline', marginBottom: 8 }}>
              <span style={{ width: 9, height: 9, borderRadius: 2, background: BAD, display: 'inline-block' }} />
              <span style={{ fontSize: 26, fontWeight: 600, color: BAD, lineHeight: 1 }}>{lost}</span>
            </div>
            <div style={{ fontSize: 10.5, color: INK_MUTED, lineHeight: 1.5 }}>
              Fora do funil de propósito: o registo não guarda em que etapa caíram, por isso distribuí-los seria inventar.
            </div>
          </div>

          <div className="panel" style={{ padding: 14 }}>
            <div className="panel-title" style={{ marginBottom: 4 }}>TENANTS VOLTARISOS</div>
            <div className="mono" style={{ fontSize: 9, color: INK_FAINT, marginBottom: 12, lineHeight: 1.5 }}>
              Pista separada · já são clientes
            </div>
            {tenantTrack.map((step, i) => {
              const base = tenantTrack[0].count;
              const width = base ? Math.max((step.count / base) * 100, step.count > 0 ? 2 : 0) : 0;
              return (
                <div key={step.label} style={{ marginBottom: i === tenantTrack.length - 1 ? 0 : 11 }}>
                  <div className="row" style={{ justifyContent: 'space-between', marginBottom: 4 }}>
                    <span className="mono" style={{ fontSize: 9.5, color: INK_MUTED, letterSpacing: 0.5 }}>{step.label}</span>
                    <span className="mono" style={{ fontSize: 10.5, color: INK, fontVariantNumeric: 'tabular-nums' }}>{step.count}</span>
                  </div>
                  <div style={{ height: 5, borderRadius: 3, background: 'rgba(255,255,255,0.04)', overflow: 'hidden' }}>
                    <div style={{ width: `${width}%`, height: '100%', background: '#4f8fe0', borderRadius: 3 }} />
                  </div>
                </div>
              );
            })}
            <div style={{ fontSize: 10, color: INK_MUTED, lineHeight: 1.5, marginTop: 12, paddingTop: 10, borderTop: `1px solid ${HAIRLINE}` }}>
              Tenants reais nunca passam pelo pipeline de fecho — entram só para receberem boas-vindas.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default FunnelView;
