import React, { useEffect, useRef } from 'react';

// Fixed core colors -- never dynamic, so this component never receives a prop that
// changes between polls. Combined with the empty effect dependency array below, the
// particle animation is set up exactly once on mount and survives every 15s refresh
// of the parent dashboard without restarting.
const ACCENT = '#f0b429';
const ACCENT2 = '#4f8fe0';

function hexToRgb(hex) {
  const h = hex.replace('#', '');
  const full = h.length === 3 ? h.split('').map(c => c + c).join('') : h;
  const n = parseInt(full, 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}

function initParticles(canvas) {
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  const rgbA = hexToRgb(ACCENT);
  const rgbB = hexToRgb(ACCENT2);
  const rand = (a, b) => a + Math.random() * (b - a);

  const inHead = (x, y) => {
    const cx = W / 2, cy = H * 0.20, r = H * 0.10;
    return (x - cx) * (x - cx) + (y - cy) * (y - cy) < r * r;
  };
  const inTorso = (x, y) => {
    const topY = H * 0.30, botY = H * 0.68;
    if (y < topY || y > botY) return false;
    const t = (y - topY) / (botY - topY);
    const halfW = (W * 0.26) * (1 - t) + (W * 0.14) * t;
    return Math.abs(x - W / 2) < halfW;
  };
  const inArms = (x, y) => {
    const shoulderY = H * 0.34, hipY = H * 0.60;
    if (y < shoulderY || y > hipY) return false;
    const t = (y - shoulderY) / (hipY - shoulderY);
    const leftCx = W / 2 - W * 0.27 - W * 0.03 * t;
    const rightCx = W / 2 + W * 0.27 + W * 0.03 * t;
    const half = W * 0.045;
    return Math.abs(x - leftCx) < half || Math.abs(x - rightCx) < half;
  };

  const particles = [];
  let tries = 0;
  while (particles.length < 240 && tries < 14000) {
    tries++;
    const x = rand(0, W), y = rand(0, H);
    if (inHead(x, y) || inTorso(x, y) || inArms(x, y)) {
      const mix = Math.random();
      particles.push({
        baseX: x, baseY: y, x, y,
        r: rand(0.8, 2.1),
        phase: rand(0, Math.PI * 2),
        speed: rand(0.4, 1.1),
        rgb: mix < 0.5 ? rgbA : rgbB,
      });
    }
  }

  const t0 = performance.now();
  let raf = null;
  const loop = (now) => {
    const t = (now - t0) / 1000;
    ctx.clearRect(0, 0, W, H);

    for (let i = 0; i < particles.length; i++) {
      const p = particles[i];
      p.x = p.baseX + Math.sin(t * p.speed + p.phase) * 2.4;
      p.y = p.baseY + Math.cos(t * p.speed * 0.8 + p.phase) * 2.4;
    }

    ctx.lineWidth = 0.5;
    for (let i = 0; i < particles.length; i++) {
      for (let j = i + 1; j < particles.length; j++) {
        const a = particles[i], b = particles[j];
        const dist = Math.hypot(a.x - b.x, a.y - b.y);
        if (dist < 13) {
          const mr = (a.rgb.r + b.rgb.r) / 2, mg = (a.rgb.g + b.rgb.g) / 2, mb = (a.rgb.b + b.rgb.b) / 2;
          ctx.strokeStyle = `rgba(${mr},${mg},${mb},${0.09 * (1 - dist / 13)})`;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }
    }

    for (let i = 0; i < particles.length; i++) {
      const p = particles[i];
      const glow = 0.5 + 0.5 * Math.sin(t * p.speed * 1.3 + p.phase);
      ctx.beginPath();
      ctx.fillStyle = `rgba(${p.rgb.r},${p.rgb.g},${p.rgb.b},${0.45 + 0.45 * glow})`;
      ctx.shadowColor = `rgba(${p.rgb.r},${p.rgb.g},${p.rgb.b},0.8)`;
      ctx.shadowBlur = 6;
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fill();
    }

    raf = requestAnimationFrame(loop);
  };
  raf = requestAnimationFrame(loop);
  return () => cancelAnimationFrame(raf);
}

function CoreHero() {
  const canvasRef = useRef(null);

  useEffect(() => {
    if (!canvasRef.current) return;
    return initParticles(canvasRef.current);
  }, []); // Empty deps: runs once on mount, regardless of how often the parent re-renders.

  return (
    <div className="panel hero-panel">
      <div className="hero-glow" style={{ background: `radial-gradient(circle at 38% 42%, ${ACCENT}26, transparent 62%), radial-gradient(circle at 64% 58%, ${ACCENT2}22, transparent 62%)` }} />
      <svg className="hero-rings" width="480" height="480" viewBox="0 0 480 480">
        <circle cx="240" cy="240" r="210" fill="none" stroke={ACCENT} strokeOpacity="0.16" strokeWidth="1" strokeDasharray="2 6" />
        <circle cx="240" cy="240" r="170" fill="none" stroke={ACCENT2} strokeOpacity="0.14" strokeWidth="1" />
      </svg>
      <canvas ref={canvasRef} className="hero-canvas" id="volt-particles" width="460" height="460" />
      <div className="hero-label">
        <div className="display hero-title">VOLT</div>
        <div className="mono hero-subtitle">NÚCLEO DE IA · v1.0</div>
      </div>
    </div>
  );
}

export default React.memo(CoreHero);
