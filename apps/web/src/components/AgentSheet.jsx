import React, { useEffect } from 'react';

/* ---------------------------------------------------------------------------
 * Ficha do agente.
 *
 * Tudo aqui sai do backend, nada é opinião: o degrau de autonomia vem de o
 * agente escrever (ou não) registos em `pending_approval`, e as credenciais vêm
 * dos imports de apps/api/app/agents/*.py. Se um agente mudar de comportamento
 * no backend, o sítio a corrigir é AGENT_SPEC.
 * ------------------------------------------------------------------------ */

const RUNGS = [
  { id: 'reactive', label: 'REATIVO', blurb: 'Só corre quando um evento o dispara.' },
  { id: 'proposes', label: 'PROPÕE · TU APROVAS', blurb: 'Escreve rascunhos que ficam à espera do teu OK.' },
  { id: 'autonomous', label: 'AUTÓNOMO', blurb: 'Corre sozinho em intervalo e grava o resultado.' },
];

// env var -> etiqueta + a integração correspondente em /api/integrations/status.
// Os `name` do lado do backend são identificadores estáveis; se algum for
// renomeado em integrations_router.py, é aqui que parte.
//
// `integration: null` faz a ficha mostrar NÃO REPORTADA -- uma credencial de que
// um agente depende mas que o endpoint não sabe verificar. Neste momento não há
// nenhuma nesse estado (o endpoint passou a cobrir as treze), mas o mecanismo
// fica, para o próximo agente que traga uma credencial nova não aparecer
// silenciosamente como se estivesse bem.
const CREDENTIALS = {
  ANTHROPIC_API_KEY: { label: 'Anthropic', integration: 'anthropic' },
  GITHUB_TOKEN: { label: 'GitHub', integration: 'github' },
  RAILWAY_TOKEN: { label: 'Railway', integration: 'railway' },
  DATABASE_URL: { label: 'Postgres', integration: 'postgres' },
  VOLTARIS_SERVICE_KEY: { label: 'VoltarisOS · chave de serviço', integration: 'voltaris' },
  VOLT_CORE_SERVICE_KEY_DAIOAKES: { label: 'Dai Oakes · chave de serviço', integration: 'daioakes' },
  VOLT_SYSTEM_STRIPE: { label: 'Stripe · mapa por sistema', integration: 'stripe' },
  VOLT_SYSTEM_REPOS: { label: 'Mapa de repositórios', integration: 'system_repos' },
  VOLT_SYSTEM_RAILWAY: { label: 'Mapa de serviços Railway', integration: 'system_railway' },
  ENTSOE_API_TOKEN: { label: 'ENTSO-E · preços de energia', integration: 'entsoe' },
  RESEND_API_KEY: { label: 'Resend · envio de email', integration: 'resend' },
};

// `tools` e `tasks` alimentam o drill-down por cluster (ClusterDrilldown.jsx):
// ferramentas em cima, agente ao centro, tarefas em baixo -- o mesmo padrão do
// TECH/FINANCES de referência.
//
// Para volt/dev_debug/database/finance/production_monitor, `tools` são nomes
// reais de função vindos de TOOL_SCHEMAS (tools.py, github_tools.py,
// database_tools.py, stripe_tools.py, railway_tools.py, voltaris_tools.py) --
// são os únicos agentes que correm num ciclo de tool-use da Anthropic. Os
// restantes sete não têm TOOL_SCHEMAS nenhum (confirmado por grep): chamam os
// clientes diretamente em Python determinístico, por isso `tools` aqui nomeia
// o sistema/cliente, não uma função. `tasks` são os modelos que cada agente
// grava, tirados dos imports em status_router.py e nos próprios *_agent.py.
const AGENT_SPEC = {
  volt: {
    rung: 'reactive',
    trigger: 'Chamada de escalonamento P1–P3 sem confirmação',
    what: 'Investiga o incidente por trás de uma chamada que ninguém confirmou — sem resposta, ocupado, falhada, ou fora da janela de SLA.',
    creds: ['ANTHROPIC_API_KEY'],
    sends: ['dev_debug', 'database'],
    tools: ['get_incident_event', 'get_recent_system_events', 'get_escalation_and_call_trail', 'get_system_monitoring_status', 'get_recent_audit_log'],
    tasks: ['Registo de investigação · voice_call_failure'],
  },
  dev_debug: {
    rung: 'reactive',
    trigger: 'Despacho do agente de incidentes',
    what: 'Diagnostica o código do sistema afetado, no repositório que o mapa VOLT_SYSTEM_REPOS resolver.',
    creds: ['ANTHROPIC_API_KEY', 'GITHUB_TOKEN', 'VOLT_SYSTEM_REPOS'],
    receives: ['volt'],
    tools: ['list_repo_files', 'read_repo_file', 'search_repo_code', 'get_recent_commits', 'get_prior_investigation'],
    tasks: ['Registo de investigação · code_diagnosis'],
  },
  database: {
    rung: 'reactive',
    trigger: 'Despacho do agente de incidentes',
    what: 'Diagnostica o Postgres do próprio Volt Core. Dispara sempre — não há mapa para resolver.',
    creds: ['ANTHROPIC_API_KEY', 'DATABASE_URL'],
    receives: ['volt'],
    tools: ['get_running_queries', 'get_slow_query_stats', 'get_table_health', 'get_unused_indexes', 'get_connection_health', 'get_backup_status'],
    tasks: ['Registo de investigação · database_diagnosis'],
  },
  finance: {
    rung: 'reactive',
    trigger: 'Investigação de natureza financeira',
    what: 'Diagnostica incidentes financeiros levantados como investigação.',
    creds: ['ANTHROPIC_API_KEY'],
    tools: ['list_recent_charges', 'list_open_disputes', 'get_account_balance', 'list_recent_payouts', 'list_subscriptions', 'get_prior_investigation'],
    tasks: ['Registo de investigação · finance_diagnosis'],
  },
  production_monitor: {
    rung: 'autonomous',
    what: 'Varre os serviços em produção no Railway, grava cada varredura e levanta alertas quando encontra problemas.',
    creds: ['ANTHROPIC_API_KEY', 'RAILWAY_TOKEN', 'VOLT_SYSTEM_RAILWAY', 'VOLTARIS_SERVICE_KEY'],
    tools: ['get_service_http_metrics', 'get_service_resource_usage', 'get_recent_deployments', 'get_voltaris_system_health', 'get_voltaris_production_readiness', 'get_voltaris_alerts', 'raise_monitoring_alert'],
    tasks: ['Varredura de monitorização', 'Alerta levantado'],
  },
  market_intelligence: {
    rung: 'autonomous',
    what: 'Recolhe preços de energia da ENTSO-E e sinais de concorrência, e grava um resumo semanal.',
    creds: ['ANTHROPIC_API_KEY', 'ENTSOE_API_TOKEN', 'VOLTARIS_SERVICE_KEY'],
    tools: ['ENTSO-E · preços de energia', 'VoltarisOS · leitura'],
    tasks: ['Relatório de mercado semanal'],
  },
  backoffice: {
    rung: 'autonomous',
    what: 'Reconcilia pagamentos e sincroniza o controlo de pagamentos da Dai Oakes, com uma allowlist própria por cima da que o painel dela já aplica.',
    creds: ['VOLT_CORE_SERVICE_KEY_DAIOAKES', 'VOLT_SYSTEM_STRIPE'],
    tools: ['Dai Oakes · controlo de pagamentos', 'Stripe'],
    tasks: ['Relatório de back office', 'Reconciliação', 'Pagamento Dai Oakes'],
  },
  sales: {
    rung: 'proposes',
    what: 'Qualifica leads e escreve o outreach. Puxa também os tenants reais da VoltarisOS, que entram só para receber boas-vindas.',
    gate: 'Os rascunhos ficam em pending_approval até carregares em Aprovar e Enviar.',
    creds: ['ANTHROPIC_API_KEY', 'VOLTARIS_SERVICE_KEY', 'RESEND_API_KEY'],
    tools: ['VoltarisOS · tenants', 'Resend · envio de email'],
    tasks: ['Lead qualificado', 'Rascunho de outreach'],
  },
  deals: {
    rung: 'proposes',
    what: 'Acompanha os negócios abertos e prepara propostas.',
    gate: 'As propostas ficam em pending_approval, e a mudança de etapa é sempre uma ação tua (confirm-stage).',
    creds: ['ANTHROPIC_API_KEY', 'VOLTARIS_SERVICE_KEY', 'VOLT_SYSTEM_STRIPE'],
    tools: ['VoltarisOS · tenants', 'Stripe', 'Resend · envio de email'],
    tasks: ['Negócio', 'Proposta', 'Sinal de expansão'],
  },
  marketing: {
    rung: 'proposes',
    what: 'Escreve conteúdo de marketing a partir do repositório.',
    gate: 'O conteúdo fica em pending_approval antes de sair.',
    creds: ['ANTHROPIC_API_KEY', 'GITHUB_TOKEN', 'VOLT_SYSTEM_REPOS'],
    tools: ['GitHub · repositório'],
    tasks: ['Conteúdo de marketing'],
  },
  customer: {
    rung: 'proposes',
    what: 'Faz triagem das perguntas de clientes e redige as respostas, sinalizando o que for sensível.',
    gate: 'As respostas ficam em pending_approval antes de seguirem.',
    creds: ['ANTHROPIC_API_KEY', 'GITHUB_TOKEN', 'VOLT_SYSTEM_REPOS'],
    tools: ['GitHub · repositório'],
    tasks: ['Query de cliente', 'Rascunho de resposta'],
  },
  operations: {
    rung: 'proposes',
    what: 'Segue os onboardings e as tarefas recorrentes, e marca o que está atrasado. Único agente sem cliente externo nenhum.',
    gate: 'Quando um passo precisa de ti, cria um pedido de ativação em pending_approval.',
    creds: ['DATABASE_URL'],
    tools: [],
    tasks: ['Onboarding', 'Pedido de ativação', 'Checkpoint recorrente'],
  },
};

const GOOD = '#8fc48a';
const BAD = '#d9614f';
const UNKNOWN = '#8a7c68';
const INK = '#f5ede0';
const INK_MUTED = '#a89680';
const HAIRLINE = 'rgba(240,180,60,0.10)';

function credentialState(envVar, integrationsByName) {
  const meta = CREDENTIALS[envVar];
  if (!meta) return { label: envVar, status: 'unknown', text: 'NÃO REPORTADA', color: UNKNOWN };
  if (meta.integration == null) {
    return { label: meta.label, status: 'unknown', text: 'NÃO REPORTADA', color: UNKNOWN };
  }
  const configured = integrationsByName[meta.integration]?.configured;
  if (configured === true) return { label: meta.label, status: 'ok', text: 'CONFIGURADA', color: GOOD };
  if (configured === false) return { label: meta.label, status: 'missing', text: 'EM FALTA', color: BAD };
  return { label: meta.label, status: 'unknown', text: 'NÃO REPORTADA', color: UNKNOWN };
}

function Section({ title, children }) {
  return (
    <div style={{ marginTop: 18 }}>
      <div className="mono" style={{ fontSize: 9.5, color: UNKNOWN, letterSpacing: 0.12 + 'em', marginBottom: 8 }}>{title}</div>
      {children}
    </div>
  );
}

function AgentSheet({ agent, company, integrations, agentLabels, onClose }) {
  useEffect(() => {
    if (!agent) return undefined;
    const onKeyDown = e => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [agent, onClose]);

  if (!agent) return null;

  const spec = AGENT_SPEC[agent.id];
  const integrationsByName = Object.fromEntries((integrations || []).map(row => [row.name, row]));
  const creds = (spec?.creds || []).map(envVar => ({ envVar, ...credentialState(envVar, integrationsByName) }));
  const unreported = creds.filter(c => c.status === 'unknown').length;
  const stateLabel = { working: 'A TRABALHAR', error: 'ERRO', idle: 'EM ESPERA' }[agent.state] || 'EM ESPERA';
  const stateColor = { working: '#f0b429', error: BAD, idle: UNKNOWN }[agent.state] || UNKNOWN;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel" onClick={e => e.stopPropagation()}>
        <div className="row" style={{ justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
          <div>
            <div className="modal-title" style={{ marginBottom: 5 }}>{agent.label}</div>
            <div className="row" style={{ gap: 10 }}>
              {company && (
                <span className="mono" style={{ fontSize: 9.5, color: company.color, letterSpacing: 0.08 + 'em' }}>{company.label}</span>
              )}
              <span className="row" style={{ gap: 5 }}>
                <span style={{ width: 7, height: 7, borderRadius: '50%', background: stateColor, display: 'inline-block' }} />
                <span className="mono" style={{ fontSize: 9.5, color: stateColor }}>{stateLabel}</span>
              </span>
            </div>
          </div>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Fechar">×</button>
        </div>

        {!spec ? (
          <div style={{ fontSize: 12, color: INK_MUTED, marginTop: 16, lineHeight: 1.6 }}>
            Este agente ainda não tem ficha. Acrescenta-o ao AGENT_SPEC em AgentSheet.jsx.
          </div>
        ) : (
          <>
            <Section title="A ESCADA">
              <div style={{ display: 'grid', gap: 6 }}>
                {RUNGS.map(rung => {
                  const isCurrent = rung.id === spec.rung;
                  return (
                    <div
                      key={rung.id}
                      style={{
                        padding: '9px 11px',
                        borderRadius: 7,
                        border: `1px solid ${isCurrent ? 'rgba(240,180,60,0.35)' : 'transparent'}`,
                        background: isCurrent ? 'rgba(240,180,60,0.07)' : 'rgba(255,255,255,0.022)',
                        opacity: isCurrent ? 1 : 0.5,
                      }}
                    >
                      <div className="row" style={{ gap: 8, marginBottom: 3 }}>
                        <span
                          style={{
                            width: 8, height: 8, borderRadius: '50%', display: 'inline-block', flexShrink: 0,
                            background: isCurrent ? '#f0b429' : 'transparent',
                            border: isCurrent ? 'none' : `1px solid ${UNKNOWN}`,
                          }}
                        />
                        <span className="mono" style={{ fontSize: 10, color: isCurrent ? '#f0b429' : INK_MUTED, letterSpacing: 0.08 + 'em' }}>
                          {rung.label}
                        </span>
                      </div>
                      <div style={{ fontSize: 11, color: INK_MUTED, paddingLeft: 16, lineHeight: 1.45 }}>{rung.blurb}</div>
                    </div>
                  );
                })}
              </div>
            </Section>

            <Section title="O QUE FAZ">
              <div style={{ fontSize: 12, color: INK, lineHeight: 1.6 }}>{spec.what}</div>
              {spec.trigger && (
                <div className="mono" style={{ fontSize: 10, color: INK_MUTED, marginTop: 8 }}>
                  DISPARA COM · {spec.trigger}
                </div>
              )}
              {spec.gate && (
                <div style={{ fontSize: 11, color: INK_MUTED, marginTop: 8, paddingLeft: 10, borderLeft: `2px solid rgba(240,180,60,0.3)`, lineHeight: 1.5 }}>
                  {spec.gate}
                </div>
              )}
            </Section>

            <Section title="CONSTRÓI SOBRE">
              <div style={{ display: 'grid', gap: 5 }}>
                {creds.map(cred => (
                  <div
                    key={cred.envVar}
                    className="row"
                    style={{ justifyContent: 'space-between', gap: 10, padding: '7px 10px', borderRadius: 6, background: 'rgba(255,255,255,0.022)' }}
                  >
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 11.5, color: INK }}>{cred.label}</div>
                      <div className="mono" style={{ fontSize: 9, color: UNKNOWN, marginTop: 2 }}>{cred.envVar}</div>
                    </div>
                    <span className="mono" style={{ fontSize: 9, color: cred.color, flexShrink: 0, letterSpacing: 0.06 + 'em' }}>
                      {cred.text}
                    </span>
                  </div>
                ))}
              </div>
              {unreported > 0 && (
                <div style={{ fontSize: 10.5, color: INK_MUTED, marginTop: 9, lineHeight: 1.5 }}>
                  {unreported === 1 ? 'Uma credencial não é' : `${unreported} credenciais não são`} reportada
                  {unreported === 1 ? '' : 's'} pelo <span className="mono" style={{ fontSize: 10 }}>/api/integrations/status</span> — não quer dizer
                  que falte, quer dizer que o painel não sabe.
                </div>
              )}
            </Section>

            {(spec.sends || spec.receives) && (
              <Section title="CADEIA">
                {spec.sends && (
                  <div style={{ fontSize: 11.5, color: INK, lineHeight: 1.6 }}>
                    Despacha para <strong style={{ color: '#f0b429' }}>{spec.sends.map(id => agentLabels[id] || id).join(' e ')}</strong> depois de investigar.
                  </div>
                )}
                {spec.receives && (
                  <div style={{ fontSize: 11.5, color: INK, lineHeight: 1.6 }}>
                    Recebe trabalho de <strong style={{ color: '#f0b429' }}>{spec.receives.map(id => agentLabels[id] || id).join(' e ')}</strong>.
                  </div>
                )}
              </Section>
            )}

            <Section title="ÚLTIMA ATIVIDADE">
              <div style={{ fontSize: 11.5, color: agent.lastActivityText ? INK_MUTED : UNKNOWN, lineHeight: 1.6 }}>
                {agent.lastActivityText || 'Sem histórico ainda.'}
              </div>
            </Section>

            <div style={{ marginTop: 18, paddingTop: 12, borderTop: `1px solid ${HAIRLINE}`, fontSize: 10, color: UNKNOWN, lineHeight: 1.5 }}>
              Degrau e credenciais derivados do backend, não escritos à mão.
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default AgentSheet;
export { AGENT_SPEC };
