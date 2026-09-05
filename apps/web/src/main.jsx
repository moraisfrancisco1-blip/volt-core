import React, { useCallback, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';
import Sidebar from './components/Sidebar.jsx';
import CoreHero from './components/CoreHero.jsx';
import SystemOverview from './components/SystemOverview.jsx';
import EventFeed from './components/EventFeed.jsx';
import AgentGrid from './components/AgentGrid.jsx';
import EscalationQueue from './components/EscalationQueue.jsx';
import QuickCommands from './components/QuickCommands.jsx';
import SystemMonitor from './components/SystemMonitor.jsx';
import InvestigationHistory from './components/InvestigationHistory.jsx';
import IntegrationsPanel from './components/IntegrationsPanel.jsx';
import MarketIntelligencePanel from './components/MarketIntelligencePanel.jsx';
import SalesPanel from './components/SalesPanel.jsx';
import DealsPanel from './components/DealsPanel.jsx';
import MarketingPanel from './components/MarketingPanel.jsx';
import DetailModal from './components/DetailModal.jsx';
import VoltCoreView from './components/views/VoltCoreView.jsx';
import AgentsView from './components/views/AgentsView.jsx';
import EscalationsView from './components/views/EscalationsView.jsx';
import EventsView from './components/views/EventsView.jsx';
import IntegrationsView from './components/views/IntegrationsView.jsx';
import DeploymentsView from './components/views/DeploymentsView.jsx';
import SettingsView from './components/views/SettingsView.jsx';

const API = (import.meta.env.VITE_API_URL || 'https://api-production-c073.up.railway.app').replace(/\/$/, '');
const INVESTIGATIONS_FETCH_LIMIT = 100;

// Mirrors each reactive agent's investigation_type -- kept in sync manually with the
// backend (apps/api/app/agents/*_runner.py and agents/status_router.py).
const AGENT_ORDER = ['volt', 'dev_debug', 'database', 'finance', 'production_monitor', 'market_intelligence', 'sales', 'deals', 'marketing'];
const AGENT_LABELS = {
  volt: ['VOLT', 'voice_call_failure'],
  dev_debug: ['DEV/DEBUG', 'code_diagnosis'],
  database: ['DATABASE', 'database_diagnosis'],
  finance: ['FINANCE', 'finance_diagnosis'],
  production_monitor: ['PRODUCTION MONITOR', null],
  market_intelligence: ['INTELIGÊNCIA DE MERCADO', null],
  sales: ['SALES', null],
  deals: ['DEALS', null],
  marketing: ['MARKETING', null],
};

function truncate(text, max = 60) {
  if (!text) return '';
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function useClock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);
  return now;
}

function App() {
  const [view, setView] = useState('dashboard');
  const [selectedDetail, setSelectedDetail] = useState(null);
  const [dashboard, setDashboard] = useState(null);
  const [events, setEvents] = useState([]);
  const [escalations, setEscalations] = useState([]);
  const [investigations, setInvestigations] = useState([]);
  const [sweeps, setSweeps] = useState([]);
  const [marketIntelReports, setMarketIntelReports] = useState([]);
  const [salesLeads, setSalesLeads] = useState([]);
  const [salesDrafts, setSalesDrafts] = useState([]);
  const [deals, setDeals] = useState([]);
  const [dealProposals, setDealProposals] = useState([]);
  const [marketingContent, setMarketingContent] = useState([]);
  const [marketingPerformance, setMarketingPerformance] = useState(null);
  const [agentsStatus, setAgentsStatus] = useState([]);
  const [integrationsStatus, setIntegrationsStatus] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const now = useClock();

  const load = useCallback(async () => {
    try {
      setError('');
      const [dashboardResponse, eventsResponse, escalationsResponse, investigationsResponse, sweepsResponse, marketIntelResponse, salesLeadsResponse, salesDraftsResponse, dealsResponse, dealProposalsResponse, marketingContentResponse, marketingPerformanceResponse, agentsStatusResponse, integrationsStatusResponse] = await Promise.all([
        fetch(`${API}/api/v1/dashboard`, { cache: 'no-store' }),
        fetch(`${API}/api/events?limit=50`, { cache: 'no-store' }),
        fetch(`${API}/api/escalations?limit=50`, { cache: 'no-store' }),
        fetch(`${API}/api/investigations?limit=${INVESTIGATIONS_FETCH_LIMIT}`, { cache: 'no-store' }),
        fetch(`${API}/api/monitoring-sweeps?limit=20`, { cache: 'no-store' }),
        fetch(`${API}/api/market-intelligence-reports?limit=10`, { cache: 'no-store' }),
        fetch(`${API}/api/sales-leads?limit=50`, { cache: 'no-store' }),
        fetch(`${API}/api/sales-outreach-drafts?limit=20`, { cache: 'no-store' }),
        fetch(`${API}/api/deals?limit=50`, { cache: 'no-store' }),
        fetch(`${API}/api/deal-proposals?limit=20`, { cache: 'no-store' }),
        fetch(`${API}/api/marketing-content?limit=20`, { cache: 'no-store' }),
        fetch(`${API}/api/marketing/performance`, { cache: 'no-store' }),
        fetch(`${API}/api/agents/status`, { cache: 'no-store' }),
        fetch(`${API}/api/integrations/status`, { cache: 'no-store' }),
      ]);
      if (!dashboardResponse.ok) throw new Error(`dashboard unavailable (${dashboardResponse.status})`);
      if (!eventsResponse.ok) throw new Error(`event history unavailable (${eventsResponse.status})`);
      if (!escalationsResponse.ok) throw new Error(`escalation queue unavailable (${escalationsResponse.status})`);
      if (!investigationsResponse.ok) throw new Error(`agent investigations unavailable (${investigationsResponse.status})`);
      if (!sweepsResponse.ok) throw new Error(`monitoring sweeps unavailable (${sweepsResponse.status})`);
      if (!marketIntelResponse.ok) throw new Error(`market intelligence reports unavailable (${marketIntelResponse.status})`);
      if (!salesLeadsResponse.ok) throw new Error(`sales leads unavailable (${salesLeadsResponse.status})`);
      if (!salesDraftsResponse.ok) throw new Error(`sales outreach drafts unavailable (${salesDraftsResponse.status})`);
      if (!dealsResponse.ok) throw new Error(`deals unavailable (${dealsResponse.status})`);
      if (!dealProposalsResponse.ok) throw new Error(`deal proposals unavailable (${dealProposalsResponse.status})`);
      if (!marketingContentResponse.ok) throw new Error(`marketing content unavailable (${marketingContentResponse.status})`);
      if (!marketingPerformanceResponse.ok) throw new Error(`marketing performance unavailable (${marketingPerformanceResponse.status})`);
      if (!agentsStatusResponse.ok) throw new Error(`agent status unavailable (${agentsStatusResponse.status})`);
      if (!integrationsStatusResponse.ok) throw new Error(`integrations status unavailable (${integrationsStatusResponse.status})`);
      setDashboard(await dashboardResponse.json());
      setEvents(await eventsResponse.json());
      setEscalations(await escalationsResponse.json());
      setInvestigations(await investigationsResponse.json());
      setSweeps(await sweepsResponse.json());
      setMarketIntelReports(await marketIntelResponse.json());
      setSalesLeads(await salesLeadsResponse.json());
      setSalesDrafts(await salesDraftsResponse.json());
      setDeals(await dealsResponse.json());
      setDealProposals(await dealProposalsResponse.json());
      setMarketingContent(await marketingContentResponse.json());
      setMarketingPerformance(await marketingPerformanceResponse.json());
      setAgentsStatus(await agentsStatusResponse.json());
      setIntegrationsStatus(await integrationsStatusResponse.json());
    } catch (err) {
      setError(err?.message || 'dashboard unavailable');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); const timer = setInterval(load, 15000); return () => clearInterval(timer); }, [load]);

  const activeEscalations = escalations.filter(item => !['completed', 'cancelled'].includes(item.status));
  const activeCritical = activeEscalations.filter(item => ['P1', 'P2'].includes(item.priority));

  const integrationsByName = Object.fromEntries(integrationsStatus.map(row => [row.name, row]));
  const twilioConfigured = integrationsByName.twilio?.configured || false;
  const railwayConfigured = integrationsByName.railway?.configured || false;

  const investigationsByType = investigations.reduce((acc, item) => {
    const list = acc[item.investigation_type] || (acc[item.investigation_type] = []);
    list.push(item);
    return acc;
  }, {});
  const statusByAgent = Object.fromEntries(agentsStatus.map(row => [row.agent, row]));
  const agentsForGrid = AGENT_ORDER.map(agentId => {
    const [label, investigationType] = AGENT_LABELS[agentId];
    const state = statusByAgent[agentId]?.state || 'idle';
    let lastActivityText = '';
    if (agentId === 'production_monitor') {
      const latest = sweeps[0];
      lastActivityText = latest ? truncate(latest.summary || latest.error || 'sem resumo') : '';
    } else if (agentId === 'market_intelligence') {
      const latest = marketIntelReports[0];
      lastActivityText = latest ? truncate(latest.error || latest.competitors_summary || 'sem resumo') : '';
    } else if (agentId === 'sales') {
      const latestLead = salesLeads[0];
      lastActivityText = latestLead ? truncate(latestLead.qualification_summary || `${latestLead.name} (${latestLead.status})`) : '';
    } else if (agentId === 'deals') {
      const latestDeal = deals[0];
      lastActivityText = latestDeal ? truncate(`Deal #${latestDeal.id} — ${latestDeal.stage}`) : '';
    } else if (agentId === 'marketing') {
      const latestContent = marketingContent[0];
      lastActivityText = latestContent ? truncate(latestContent.title || 'sem título') : '';
    } else {
      const latest = (investigationsByType[investigationType] || [])[0];
      lastActivityText = latest ? truncate((latest.status === 'failed' ? latest.error : latest.hypothesis) || 'sem resumo') : '';
    }
    return { id: agentId, label, state, lastActivityText };
  });

  const systemOk = (dashboard?.core === 'online') && activeCritical.length === 0;

  // --- Detail modal builders -- one per record type, all data already in state ---
  const openEventDetail = item => setSelectedDetail({
    title: item.title || item.message,
    fields: [
      { label: 'ID', value: item.id }, { label: 'Sistema', value: item.system_id || item.system },
      { label: 'Prioridade', value: item.priority }, { label: 'Estado', value: item.status },
      { label: 'Tipo', value: item.event_type }, { label: 'Mensagem', value: item.message },
      { label: 'Ação recomendada', value: item.recommended_action },
      { label: 'Recebido em', value: item.received_at || item.created_at },
    ],
  });
  const openEscalationDetail = item => setSelectedDetail({
    title: `${item.system} — ${item.action}`,
    fields: [
      { label: 'ID', value: item.id }, { label: 'Evento', value: item.event_id },
      { label: 'Prioridade', value: item.priority }, { label: 'Estado', value: item.status },
      { label: 'Tentativas de chamada', value: item.call_attempts }, { label: 'SLA (min)', value: item.sla_minutes },
      { label: 'Prazo', value: item.due_at }, { label: 'Fora do prazo', value: item.overdue ? 'sim' : 'não' },
    ],
  });
  const openInvestigationDetail = item => setSelectedDetail({
    title: `${item.investigation_type} — ${item.system}`,
    fields: [
      { label: 'ID', value: item.id }, { label: 'Estado', value: item.status },
      { label: 'Hipótese', value: item.hypothesis }, { label: 'Próximo passo', value: item.recommended_next_step },
      { label: 'Confiança', value: item.confidence }, { label: 'Padrão conhecido', value: item.is_known_pattern == null ? '—' : (item.is_known_pattern ? 'sim' : 'não') },
      { label: 'Erro', value: item.error }, { label: 'Concluída em', value: item.completed_at },
    ],
  });
  const openLeadDetail = item => setSelectedDetail({
    title: item.name,
    fields: [
      { label: 'Tipo', value: item.lead_type }, { label: 'Estado', value: item.status },
      { label: 'Email', value: item.email }, { label: 'Empresa', value: item.company },
      { label: 'Fit', value: item.fit_score }, { label: 'Resumo de qualificação', value: item.qualification_summary },
      { label: 'Próximo passo sugerido', value: item.suggested_next_step }, { label: 'Contexto', value: item.context },
    ],
  });
  const openDealDetail = item => setSelectedDetail({
    title: `Deal #${item.id}`,
    fields: [
      { label: 'Estágio', value: item.stage }, { label: 'Lead', value: item.lead_id },
      { label: 'Sugestão de fecho', value: item.suggested_stage }, { label: 'Razão da sugestão', value: item.suggested_stage_reason },
      { label: 'Parado', value: item.stale ? 'sim' : 'não' }, { label: 'Estágio mudou em', value: item.stage_changed_at },
    ],
  });
  const openContentDetail = item => setSelectedDetail({
    title: item.title,
    fields: [
      { label: 'Tipo', value: item.content_type }, { label: 'Formato', value: item.format },
      { label: 'Audiência', value: item.audience }, { label: 'Estado', value: item.status },
      { label: 'Fontes', value: item.source_facts }, { label: 'Variante de', value: item.parent_content_id },
      { label: 'Corpo', value: item.body },
    ],
  });

  const triggerInvestigationViaPrompt = async () => {
    const systemId = window.prompt('Nome do sistema a investigar:');
    if (!systemId) return;
    try {
      const response = await fetch(`${API}/api/investigations/trigger-manual`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ system_id: systemId }),
      });
      if (response.ok) load();
    } catch { /* footer CTA has no inline error state -- silent failure is acceptable here */ }
  };

  const renderMainContent = () => {
    if (view === 'volt-core') {
      return (
        <VoltCoreView
          investigations={investigations} twilioConfigured={twilioConfigured} agentsStatus={agentsStatus}
          systemOk={systemOk} events={events} fetchLimit={INVESTIGATIONS_FETCH_LIMIT} onSelectEvent={openEventDetail}
        />
      );
    }
    if (view === 'agents') {
      return (
        <AgentsView
          agents={agentsForGrid} investigations={investigations} salesLeads={salesLeads} deals={deals} marketingContent={marketingContent}
          onSelectInvestigation={openInvestigationDetail} onSelectLead={openLeadDetail} onSelectDeal={openDealDetail} onSelectContent={openContentDetail}
        />
      );
    }
    if (view === 'escalations') return <EscalationsView escalations={escalations} onSelect={openEscalationDetail} />;
    if (view === 'events') return <EventsView events={events} onSelect={openEventDetail} />;
    if (view === 'integrations') return <IntegrationsView integrations={integrationsStatus} railwayConfigured={railwayConfigured} />;
    if (view === 'deployments') return <DeploymentsView />;
    if (view === 'settings') return <SettingsView integrations={integrationsStatus} />;

    return (
      <>
        <div className="row-1">
          <SystemOverview
            investigationCount={investigations.length}
            twilioConfigured={twilioConfigured}
            agentsStatus={agentsStatus}
            systemOk={systemOk}
            iconColor="#f0b429"
          />
          <CoreHero />
          <EventFeed events={events} onSelect={openEventDetail} />
        </div>

        <div className="row-2">
          <AgentGrid agents={agentsForGrid} onSelect={agent => setView('agents')} />
          <EscalationQueue escalations={activeEscalations} onSelect={openEscalationDetail} />
          <QuickCommands apiBase={API} systems={dashboard?.systems} onInvestigationTriggered={load} />
        </div>

        <div className="row-3">
          <SystemMonitor railwayConfigured={railwayConfigured} />
          <InvestigationHistory investigations={investigations} fetchLimit={INVESTIGATIONS_FETCH_LIMIT} />
          <IntegrationsPanel integrations={integrationsStatus} />
        </div>

        <div className="row-4">
          <MarketIntelligencePanel reports={marketIntelReports} />
        </div>

        <div className="row-4">
          <SalesPanel
            leads={salesLeads}
            drafts={salesDrafts}
            apiBase={API}
            onDraftUpdated={updated => setSalesDrafts(prev => prev.map(d => (d.id === updated.id ? updated : d)))}
            onSelectLead={openLeadDetail}
          />
        </div>

        <div className="row-4">
          <DealsPanel
            deals={deals}
            proposals={dealProposals}
            apiBase={API}
            onProposalUpdated={updated => setDealProposals(prev => prev.map(p => (p.id === updated.id ? updated : p)))}
            onDealUpdated={updated => setDeals(prev => prev.map(d => (d.id === updated.id ? updated : d)))}
            onSelectDeal={openDealDetail}
          />
        </div>

        <div className="row-4">
          <MarketingPanel
            content={marketingContent}
            performance={marketingPerformance}
            apiBase={API}
            onContentUpdated={updated => setMarketingContent(prev => prev.map(c => (c.id === updated.id ? updated : c)))}
            onRepurposeRequested={() => setTimeout(load, 4000)}
            onSelectContent={openContentDetail}
          />
        </div>
      </>
    );
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="row" style={{ gap: 12 }}>
          <div className="brand-mark">
            <svg width="16" height="16" viewBox="0 0 24 24"><path d="M13 2 4 14h6l-1 8 9-12h-6z" fill="#120e0a" /></svg>
          </div>
          <div>
            <div className="display brand-name">VOLT</div>
            <div className="mono brand-sub">COMMAND CENTER</div>
          </div>
        </div>

        <div className="row system-pill">
          <span className="system-pill-dot" />
          <span className="mono system-pill-text">SISTEMA · {dashboard?.core === 'online' ? 'OPERACIONAL' : loading ? 'A VERIFICAR' : 'OFFLINE'}</span>
        </div>

        <div className="mono topbar-datetime">
          <div className="topbar-date">{now.toLocaleDateString('pt-PT', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}</div>
          <div className="topbar-time">{now.toLocaleTimeString('pt-PT')}</div>
        </div>

        <div className="row topbar-icons">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#a89680" strokeWidth="1.7"><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" /></svg>
          <div style={{ position: 'relative' }}>
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#a89680" strokeWidth="1.7"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.7 21a2 2 0 0 1-3.4 0" /></svg>
            {activeCritical.length > 0 && <span className="notif-dot" />}
          </div>
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#a89680" strokeWidth="1.7"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6V21a2 2 0 1 1-4 0v-.2a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.6-1H3a2 2 0 1 1 0-4h.2a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.6V3a2 2 0 1 1 4 0v.2a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.6 1H21a2 2 0 1 1 0 4h-.2a1.7 1.7 0 0 0-1.5 1z" /></svg>
          <div className="row avatar-block">
            <div className="mono avatar-circle">FM</div>
            <div>
              <div className="avatar-name">Francisco</div>
              <div className="mono avatar-role">OPERADOR</div>
            </div>
          </div>
        </div>
      </header>

      <div className="body-row">
        <Sidebar twilioConfigured={twilioConfigured} activeView={view} onNavigate={setView} apiBase={API} />

        <div className="main-content">
          {renderMainContent()}

          <div className="row footer-row">
            <div className="row mono footer-meta">
              <span>Schiedam, NL</span>
              <span>·</span>
              <span>Ambiente: {dashboard?.mode === 'observe' ? 'Produção' : dashboard?.mode || '—'}</span>
              <span>·</span>
              <span>{error ? 'Erro na última atualização' : loading ? 'A carregar…' : 'Atualizado agora'}</span>
            </div>
            <button type="button" className="row footer-cta" style={{ border: 'none', cursor: 'pointer' }} onClick={triggerInvestigationViaPrompt}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#14100c" strokeWidth="2.2"><path d="M12 5v14M5 12h14" /></svg>
              <span className="mono footer-cta-text">NOVA INVESTIGAÇÃO</span>
            </button>
          </div>
        </div>
      </div>

      <DetailModal detail={selectedDetail} onClose={() => setSelectedDetail(null)} />
    </div>
  );
}

createRoot(document.getElementById('root')).render(<App />);
