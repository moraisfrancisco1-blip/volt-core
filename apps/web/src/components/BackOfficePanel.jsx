import React from 'react';

const SOURCE_LABEL = {
  stripe_sandbox: 'DADOS SANDBOX -- NÃO É RECEITA REAL',
  no_source_configured: 'SEM DADOS FINANCEIROS AINDA',
  stripe_unavailable: 'STRIPE INDISPONÍVEL',
};
const SOURCE_COLOR = {
  stripe_sandbox: '#f0b429',
  no_source_configured: '#7d7062',
  stripe_unavailable: '#d9614f',
};

// Payment Control (Dai Oakes) is a completely separate business and data source from the
// VoltarisOS/Stripe-sandbox reconciliation above -- its own label set, never reused, so
// the two can never be visually confused as coming from the same place.
const PAYMENT_CONTROL_LABEL = {
  dai_oakes_real: 'DADOS REAIS -- DAI OAKES',
  no_source_configured: 'SEM DADOS FINANCEIROS AINDA',
  dai_oakes_unavailable: 'DAI OAKES INDISPONÍVEL',
};
const PAYMENT_CONTROL_COLOR = {
  dai_oakes_real: '#8fc48a',
  no_source_configured: '#7d7062',
  dai_oakes_unavailable: '#d9614f',
};

function ReconciliationRow({ record, onSelect }) {
  return (
    <div
      className={`feed-item${onSelect ? ' clickable-row' : ''}`}
      style={{ borderLeftColor: '#d9614f' }}
      onClick={onSelect ? () => onSelect(record) : undefined}
    >
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <span className="mono feed-item-tag" style={{ color: '#d9614f' }}>Deal #{record.deal_id}</span>
        <span className="mono feed-item-time">{SOURCE_LABEL[record.data_source] || record.data_source}</span>
      </div>
      <div className="feed-item-text">{record.note}</div>
    </div>
  );
}

function PaymentControlRow({ payment }) {
  const paid = ['paid', 'succeeded'].includes((payment.status || '').toLowerCase());
  return (
    <div className="feed-item" style={{ borderLeftColor: paid ? '#8fc48a' : '#f0b429' }}>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <span className="mono feed-item-tag" style={{ color: paid ? '#8fc48a' : '#f0b429' }}>{payment.status}</span>
        <span className="mono feed-item-time">DAI OAKES REAL</span>
      </div>
      <div className="feed-item-text">
        {payment.external_id} -- {payment.amount != null ? `${payment.amount} ${(payment.currency || '').toUpperCase()}` : 'sem valor'}
      </div>
    </div>
  );
}

function BackOfficePanel({ report, reconciliations, paymentControlSummary, paymentControlPayments, onSelectReconciliation }) {
  const unmatched = (reconciliations || []).filter(r => !r.match_found).slice(0, 6);
  const sourceColor = report ? (SOURCE_COLOR[report.data_source] || '#7d7062') : '#7d7062';
  const pcSource = paymentControlSummary?.source;
  const pcColor = PAYMENT_CONTROL_COLOR[pcSource] || '#7d7062';
  const recentPayments = (paymentControlPayments || []).slice(0, 5);

  return (
    <div className="panel">
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
        <div className="panel-title" style={{ margin: 0 }}>BACK OFFICE</div>
        {report && <span className="mono feed-item-time" style={{ color: sourceColor }}>{SOURCE_LABEL[report.data_source] || report.data_source}</span>}
      </div>

      <div className="panel-row-item" style={{ padding: 12, marginBottom: 16 }}>
        <div className="mono panel-title" style={{ marginBottom: 6 }}>RELATÓRIO INTERNO -- VOLTARISOS (SANDBOX)</div>
        {report
          ? (
            <>
              <div className="feed-item-text" style={{ marginBottom: 6 }}>{report.summary}</div>
              <div className="row" style={{ gap: 16 }}>
                <span className="mono feed-item-time">Fechados: {report.deals_closed_count}</span>
                <span className="mono feed-item-time">Com fatura: {report.deals_matched_count}</span>
                <span className="mono feed-item-time">Sem correspondência: {report.deals_unmatched_count}</span>
              </div>
            </>
          )
          : <div className="empty-state">Sem relatório gerado ainda.</div>}
      </div>

      <div className="mono panel-title" style={{ marginBottom: 8 }}>
        DEALS SEM CORRESPONDÊNCIA FINANCEIRA {unmatched.length > 0 ? `(${unmatched.length})` : ''}
      </div>
      {unmatched.length === 0
        ? <div className="empty-state">Sem discrepâncias sinalizadas.</div>
        : (
          <div className="feed-list" style={{ marginBottom: 16 }}>
            {unmatched.map(record => <ReconciliationRow record={record} onSelect={onSelectReconciliation} key={record.id} />)}
          </div>
        )}

      {/* Payment Control (Dai Oakes) -- a completely separate business, own real data
          source, deliberately never merged with the VoltarisOS sandbox section above. */}
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 8, marginTop: 4 }}>
        <div className="mono panel-title" style={{ margin: 0 }}>PAYMENT CONTROL -- DAI OAKES</div>
        {pcSource && <span className="mono feed-item-time" style={{ color: pcColor }}>{PAYMENT_CONTROL_LABEL[pcSource] || pcSource}</span>}
      </div>
      {paymentControlSummary?.security_incident && (
        <div className="panel-row-item" style={{ padding: 12, marginBottom: 8, borderColor: '#d9614f' }}>
          <div className="mono feed-item-tag" style={{ color: '#d9614f', marginBottom: 4 }}>INCIDENTE DE SEGURANÇA</div>
          <div className="feed-item-text">{paymentControlSummary.note}</div>
        </div>
      )}
      {!paymentControlSummary || paymentControlSummary.total === 0
        ? <div className="empty-state">{paymentControlSummary?.note || 'sem dados financeiros ainda'}</div>
        : (
          <>
            <div className="row" style={{ gap: 16, marginBottom: 8 }}>
              <span className="mono feed-item-time">Total: {paymentControlSummary.total}</span>
              <span className="mono feed-item-time">Pagos: {paymentControlSummary.paid}</span>
              <span className="mono feed-item-time">Pendentes: {paymentControlSummary.pending}</span>
            </div>
            <div className="feed-list">
              {recentPayments.map(payment => <PaymentControlRow payment={payment} key={payment.id} />)}
            </div>
          </>
        )}
    </div>
  );
}

export default BackOfficePanel;
