import React, { useState } from 'react';

function OnboardingRow({ onboarding, apiBase, onUpdated, onSelect }) {
  const [stepState, setStepState] = useState({}); // step_id -> idle|completing|error

  const completeStep = async step => {
    setStepState(prev => ({ ...prev, [step.id]: 'completing' }));
    try {
      const response = await fetch(`${apiBase}/api/onboardings/${onboarding.id}/steps/${step.id}/complete`, { method: 'POST' });
      const payload = await response.json();
      if (response.ok) onUpdated(payload);
      setStepState(prev => ({ ...prev, [step.id]: response.ok ? 'idle' : 'error' }));
    } catch {
      setStepState(prev => ({ ...prev, [step.id]: 'error' }));
    }
  };

  return (
    <div className="panel-row-item" style={{ padding: 12, marginBottom: 8 }}>
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
        <span className={`agent-card-name${onSelect ? ' clickable-row' : ''}`} onClick={onSelect ? () => onSelect(onboarding) : undefined}>
          Onboarding — Deal #{onboarding.deal_id}
        </span>
        <span className="mono feed-item-time">{onboarding.progress.done}/{onboarding.progress.total} passos</span>
      </div>
      <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
        {onboarding.steps.map(step => {
          const done = step.status === 'done';
          const busy = stepState[step.id] === 'completing';
          return (
            <button
              key={step.id}
              type="button"
              className="row panel-row-item command-row-button"
              style={{
                padding: '6px 10px', opacity: busy ? 0.6 : 1,
                borderColor: done ? '#8fc48a' : step.requires_activation ? '#e0793c' : undefined,
                cursor: done || step.requires_activation ? 'default' : 'pointer',
              }}
              onClick={done || step.requires_activation || busy ? undefined : () => completeStep(step)}
              disabled={busy}
            >
              <span className="mono" style={{ fontSize: 10.5, color: done ? '#8fc48a' : step.requires_activation ? '#e0793c' : '#a89680' }}>
                {done ? '✓' : step.requires_activation ? '⏳' : '○'} {step.label}
              </span>
            </button>
          );
        })}
      </div>
      {onboarding.stalled && <div className="mono feed-item-time" style={{ color: '#e0793c', marginTop: 8 }}>Parado há vários dias sem progresso.</div>}
    </div>
  );
}

function ActivationRow({ activation, apiBase, onUpdated }) {
  const [state, setState] = useState('idle'); // idle | approving | done | error

  const approve = async () => {
    setState('approving');
    try {
      const response = await fetch(`${apiBase}/api/operations-activations/${activation.id}/approve`, { method: 'POST' });
      const payload = await response.json();
      onUpdated(payload);
      setState(payload.status === 'approved' ? 'done' : 'error');
    } catch {
      setState('error');
    }
    setTimeout(() => setState('idle'), 4000);
  };

  const isPending = activation.status === 'pending_approval';
  const label = state === 'approving' ? 'A APROVAR…' : state === 'done' ? 'ATIVADO' : state === 'error' ? 'FALHOU' : 'Aprovar Ativação';

  return (
    <div className="panel-row-item" style={{ padding: 12, marginBottom: 8 }}>
      <div className="feed-item-text" style={{ marginBottom: 8 }}>{activation.description}</div>
      {isPending && (
        <button
          type="button"
          className="row panel-row-item command-row actionable command-row-button"
          style={{ opacity: state === 'approving' ? 0.7 : 1 }}
          onClick={approve}
          disabled={state === 'approving'}
        >
          <span className="command-label">{label}</span>
        </button>
      )}
    </div>
  );
}

function RecurringTaskRow({ task }) {
  const color = task.overdue ? '#e0793c' : task.due_soon ? '#f0b429' : '#8fc48a';
  const status = task.overdue ? `atrasado ${Math.abs(task.days_until_due)}d` : task.due_soon ? `em breve (${task.days_until_due}d)` : `em dia (${task.days_until_due}d)`;
  return (
    <div className="feed-item" style={{ borderLeftColor: color }}>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <span className="mono feed-item-tag" style={{ color }}>{status}</span>
        <span className="mono feed-item-time">cada {task.cadence_days}d</span>
      </div>
      <div className="feed-item-text">{task.name}</div>
    </div>
  );
}

function OperationsPanel({ onboardings, activations, recurringTasks, apiBase, onOnboardingUpdated, onActivationUpdated, onSelectOnboarding }) {
  const activeOnboardings = (onboardings || []).filter(o => !o.completed_at).slice(0, 4);
  const pendingActivations = (activations || []).filter(a => a.status === 'pending_approval').slice(0, 4);
  const flaggedTasks = (recurringTasks || []).filter(t => t.overdue || t.due_soon);

  return (
    <div className="panel">
      <div className="panel-title" style={{ marginBottom: 12 }}>OPERATIONS</div>

      <div className="row" style={{ gap: 16, alignItems: 'flex-start' }}>
        <div style={{ flex: 1 }}>
          <div className="mono panel-title" style={{ marginBottom: 8 }}>
            ONBOARDING EM CURSO {activeOnboardings.length > 0 ? `(${activeOnboardings.length})` : ''}
          </div>
          {activeOnboardings.length === 0
            ? <div className="empty-state">Sem onboardings em curso.</div>
            : activeOnboardings.map(o => (
                <OnboardingRow onboarding={o} apiBase={apiBase} onUpdated={onOnboardingUpdated} onSelect={onSelectOnboarding} key={o.id} />
              ))}
        </div>

        <div style={{ flex: 1 }}>
          <div className="mono panel-title" style={{ marginBottom: 8 }}>
            ATIVAÇÕES PENDENTES DE APROVAÇÃO {pendingActivations.length > 0 ? `(${pendingActivations.length})` : ''}
          </div>
          {pendingActivations.length === 0
            ? <div className="empty-state">Sem ativações pendentes.</div>
            : pendingActivations.map(a => <ActivationRow activation={a} apiBase={apiBase} onUpdated={onActivationUpdated} key={a.id} />)}

          <div className="mono panel-title" style={{ margin: '16px 0 8px' }}>
            TAREFAS RECORRENTES {flaggedTasks.length > 0 ? `(${flaggedTasks.length})` : ''}
          </div>
          {flaggedTasks.length === 0
            ? <div className="empty-state">Sem tarefas recorrentes atrasadas ou próximas.</div>
            : <div className="feed-list">{flaggedTasks.map(t => <RecurringTaskRow task={t} key={t.name} />)}</div>}
        </div>
      </div>
    </div>
  );
}

export default OperationsPanel;
