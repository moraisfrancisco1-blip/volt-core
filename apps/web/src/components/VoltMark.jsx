import React, { useId } from 'react';

// The VoltarisOS brand mark: a tapered "V" -- a smooth left wing and a jagged
// lightning-bolt right stroke, both converging to the same point -- approximating the
// real logo (gold-to-orange gradient) since only a rendered image was available, not a
// source file. Renders a <g>, not a <svg>, so it can be embedded either standalone
// (wrapped in its own small <svg>) or nested inside a larger scene like the VOLTCORE hub.
function VoltMark({ id }) {
  const autoId = useId();
  const uid = id || autoId;

  return (
    <g>
      <defs>
        <linearGradient id={`volt-mark-wing-${uid}`} x1="0" y1="0" x2="0.4" y2="1">
          <stop offset="0%" stopColor="#ffd766" />
          <stop offset="100%" stopColor="#e0793c" />
        </linearGradient>
        <linearGradient id={`volt-mark-bolt-${uid}`} x1="1" y1="0" x2="0.3" y2="1">
          <stop offset="0%" stopColor="#f7a83c" />
          <stop offset="100%" stopColor="#d9622a" />
        </linearGradient>
      </defs>
      <path d="M2,2 C-4,40 6,70 49,92 C34,62 20,30 2,2 Z" fill={`url(#volt-mark-wing-${uid})`} />
      <path d="M108,2 L72,48 L86,52 L51,92 L78,54 L64,50 L100,8 Z" fill={`url(#volt-mark-bolt-${uid})`} />
    </g>
  );
}

export default VoltMark;
