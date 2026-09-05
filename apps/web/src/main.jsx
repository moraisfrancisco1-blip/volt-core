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

const API = (import.meta.env.VITE_API_URL || 'https://api-production-c073.up.railway.app').replace(/\/$/, '');
const INVESTIGATIONS_FETCH_LIMIT = 100;

// Mirrors each reactive agent's investigation_type -- kept in sync manually with the
// backend (apps/api/app/agents/*_runner.py and agents/status_router.py).
const AGENT_ORDER = ['volt', 'dev_debug', 'database', 'finance', 'production_monitor', 'market_intelligence', 'sales', 'deals'];
const AGENT_LABELS = {
  volt: ['VOLT', 'voice_call_failure'],
  dev_debug: ['DEV/DEBUG', 'code_diagnosis'],
  database: ['DATABASE', 'database_diagnosis'],
  finance: ['FINANCE', 'finance_diagnosis'],
  production_monitor: ['PRODUCTION MONITOR', null],
  market_intelligence: ['INTELIGÊNCIA DE MERCADO', null],
  sales: ['SALES', null],
  deals: ['DEALS', null],
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
  const [agentsStatus, setAgentsStatus] = useState([]);
  const [integrationsStatus, setIntegrationsStatus] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const now = useClock();

  const load = useCallback(async () => {
    try {
      setError('');
      const [dashboardResponse, eventsResponse, escalationsResponse, investigationsResponse, sweepsResponse, marketIntelResponse, salesLeadsResponse, salesDraftsResponse, dealsResponse, dealProposalsResponse, agentsStatusResponse, integrationsStatusResponse] = await Promise.all([
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
    } else {
      const latest = (investigationsByType[investigationType] || [])[0];
      lastActivityText = latest ? truncate((latest.status === 'failed' ? latest.error : latest.hypothesis) || 'sem resumo') : '';
    }
    return { id: agentId, label, state, lastActivityText };
  });

  const systemOk = (dashboard?.core === 'online') && activeCritical.length === 0;

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
        <Sidebar twilioConfigured={twilioConfigured} />

        <div className="main-content">
          <div className="row-1">
            <SystemOverview
              investigationCount={investigations.length}
              twilioConfigured={twilioConfigured}
              agentsStatus={agentsStatus}
              systemOk={systemOk}
              iconColor="#f0b429"
            />
            <CoreHero />
            <EventFeed events={events} />
          </div>

          <div className="row-2">
            <AgentGrid agents={agentsForGrid} />
            <EscalationQueue escalations={activeEscalations} />
            <QuickCommands apiBase={API} />
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
            />
          </div>

          <div className="row-4">
            <DealsPanel
              deals={deals}
              proposals={dealProposals}
              apiBase={API}
              onProposalUpdated={updated => setDealProposals(prev => prev.map(p => (p.id === updated.id ? updated : p)))}
              onDealUpdated={updated => setDeals(prev => prev.map(d => (d.id === updated.id ? updated : d)))}
            />
          </div>

          <div className="row footer-row">
            <div className="row mono footer-meta">
              <span>Schiedam, NL</span>
              <span>·</span>
              <span>Ambiente: {dashboard?.mode === 'observe' ? 'Produção' : dashboard?.mode || '—'}</span>
              <span>·</span>
              <span>{error ? 'Erro na última atualização' : loading ? 'A carregar…' : 'Atualizado agora'}</span>
            </div>
            <div className="row footer-cta">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#14100c" strokeWidth="2.2"><path d="M12 5v14M5 12h14" /></svg>
              <span className="mono footer-cta-text">NOVA INVESTIGAÇÃO</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

createRoot(document.getElementById('root')).render(<App />);
