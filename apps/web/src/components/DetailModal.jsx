import React, { useEffect } from 'react';

function DetailModal({ detail, onClose }) {
  useEffect(() => {
    if (!detail) return undefined;
    const onKeyDown = e => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [detail, onClose]);

  if (!detail) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel" onClick={e => e.stopPropagation()}>
        <div className="row" style={{ justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
          <div className="modal-title">{detail.title}</div>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Fechar">×</button>
        </div>
        {(detail.fields || []).map((field, i) => (
          <div className="modal-field" key={i}>
            <div className="mono modal-field-label">{field.label}</div>
            <div className="modal-field-value">{field.value ?? '—'}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default DetailModal;
