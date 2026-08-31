import React, { useEffect, useRef } from 'react';

// Fixed core colors -- never dynamic, so this component never receives a prop that
// changes between polls. Combined with the empty effect dependency array below, the
// canvas animation is set up exactly once on mount and survives every 15s refresh of
// the parent dashboard without restarting.
const ACCENT = '#f0b429';
const ACCENT2 = '#4f8fe0';

function hexToRgb(hex) {
  const h = hex.replace('#', '');
  const full = h.length === 3 ? h.split('').map(c => c + c).join('') : h;
  const n = parseInt(full, 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}

// Original, generic head+shoulder profile (not any real person) drawn as a
// translucent wireframe with a PCB-style circuit lattice glowing inside it -- a
// holographic "digital being" head, built from scratch in canvas paths.
function headPath(ctx, W, H) {
  const P = (xf, yf) => [W * xf, H * yf];
  ctx.beginPath();
  ctx.moveTo(...P(0.50, 0.085));
  ctx.bezierCurveTo(...P(0.40, 0.09), ...P(0.335, 0.13), ...P(0.315, 0.205));
  ctx.bezierCurveTo(...P(0.30, 0.26), ...P(0.305, 0.30), ...P(0.315, 0.325));
  ctx.bezierCurveTo(...P(0.33, 0.335), ...P(0.345, 0.335), ...P(0.35, 0.355));
  ctx.bezierCurveTo(...P(0.352, 0.375), ...P(0.335, 0.385), ...P(0.325, 0.375));
  ctx.bezierCurveTo(...P(0.315, 0.40), ...P(0.32, 0.43), ...P(0.35, 0.455));
  ctx.bezierCurveTo(...P(0.37, 0.485), ...P(0.375, 0.50), ...P(0.30, 0.545));
  ctx.bezierCurveTo(...P(0.18, 0.60), ...P(0.14, 0.72), ...P(0.13, 1.0));
  ctx.lineTo(...P(0.87, 1.0));
  ctx.bezierCurveTo(...P(0.86, 0.72), ...P(0.82, 0.60), ...P(0.70, 0.545));
  ctx.bezierCurveTo(...P(0.635, 0.51), ...P(0.615, 0.49), ...P(0.615, 0.465));
  ctx.bezierCurveTo(...P(0.62, 0.478), ...P(0.605, 0.485), ...P(0.585, 0.478));
  ctx.bezierCurveTo(...P(0.60, 0.465), ...P(0.615, 0.455), ...P(0.625, 0.44));
  ctx.bezierCurveTo(...P(0.635, 0.425), ...P(0.635, 0.41), ...P(0.645, 0.40));
  ctx.bezierCurveTo(...P(0.685, 0.385), ...P(0.695, 0.36), ...P(0.665, 0.34));
  ctx.bezierCurveTo(...P(0.65, 0.325), ...P(0.645, 0.28), ...P(0.64, 0.25));
  ctx.bezierCurveTo(...P(0.665, 0.24), ...P(0.675, 0.215), ...P(0.66, 0.19));
  ctx.bezierCurveTo(...P(0.65, 0.15), ...P(0.60, 0.10), ...P(0.50, 0.085));
  ctx.closePath();
}

// Faint underlying facial contour (eyes, nose, mouth, ear) -- stylized, not any
// real person, drawn thin and dim so the dense circuit lattice stays the dominant
// texture on top, the same way the reference art keeps a face readable under a
// dense PCB pattern rather than erasing it.
function facialFeatures(ctx, W, H) {
  const P = (xf, yf) => [W * xf, H * yf];
  ctx.beginPath();
  ctx.moveTo(...P(0.375, 0.295));
  ctx.quadraticCurveTo(...P(0.415, 0.278), ...P(0.455, 0.298));
  ctx.quadraticCurveTo(...P(0.415, 0.312), ...P(0.375, 0.295));
  ctx.moveTo(...P(0.535, 0.285));
  ctx.quadraticCurveTo(...P(0.565, 0.272), ...P(0.59, 0.288));
  ctx.quadraticCurveTo(...P(0.565, 0.30), ...P(0.535, 0.285));
  ctx.moveTo(...P(0.475, 0.305));
  ctx.quadraticCurveTo(...P(0.455, 0.35), ...P(0.45, 0.385));
  ctx.quadraticCurveTo(...P(0.455, 0.398), ...P(0.47, 0.395));
  ctx.moveTo(...P(0.405, 0.44));
  ctx.quadraticCurveTo(...P(0.46, 0.462), ...P(0.515, 0.442));
  ctx.moveTo(...P(0.655, 0.315));
  ctx.bezierCurveTo(...P(0.685, 0.32), ...P(0.69, 0.35), ...P(0.665, 0.365));
  ctx.bezierCurveTo(...P(0.68, 0.345), ...P(0.675, 0.325), ...P(0.655, 0.315));
}

// Interpolates a point along a polyline trace by cumulative distance -- used to
// place the traveling pulses along a subset of circuit traces.
function tracePoint(path, t) {
  let lens = path._lens;
  if (!lens) {
    lens = [0];
    for (let i = 1; i < path.length; i++) lens.push(lens[i - 1] + Math.hypot(path[i].x - path[i - 1].x, path[i].y - path[i - 1].y));
    path._lens = lens;
  }
  const total = lens[lens.length - 1];
  if (total <= 0) return path[0];
  const target = t * total;
  let i = 1;
  while (i < lens.length && lens[i] < target) i++;
  if (i >= lens.length) return path[path.length - 1];
  const segLen = lens[i] - lens[i - 1];
  const segT = segLen > 0 ? (target - lens[i - 1]) / segLen : 0;
  const a = path[i - 1], b = path[i];
  return { x: a.x + (b.x - a.x) * segT, y: a.y + (b.y - a.y) * segT };
}

function initCore(canvas) {
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  const rgbA = hexToRgb(ACCENT);
  const rgbB = hexToRgb(ACCENT2);
  const rand = (a, b) => a + Math.random() * (b - a);

  // Build a node grid confined to the head silhouette, then random-walk
  // PCB-style traces across it (orthogonal hops, occasional turns). A finer grid
  // and higher trace count than the original port -- a dense lattice is what
  // reads as "circuit-covered face" rather than a handful of scattered lines.
  headPath(ctx, W, H);
  const cell = 6;
  const nodes = new Map();
  const gxMin = Math.floor(W * 0.28 / cell), gxMax = Math.ceil(W * 0.72 / cell);
  const gyMin = Math.floor(H * 0.08 / cell), gyMax = Math.ceil(H * 1.0 / cell);
  for (let gx = gxMin; gx <= gxMax; gx++) {
    for (let gy = gyMin; gy <= gyMax; gy++) {
      const x = gx * cell, y = gy * cell;
      if (ctx.isPointInPath(x, y)) nodes.set(gx + ',' + gy, { x, y, gx, gy });
    }
  }
  const nodeList = [...nodes.values()];
  const traces = [];
  const traceCount = Math.min(140, Math.floor(nodeList.length * 0.14));
  for (let i = 0; i < traceCount; i++) {
    const start = nodeList[Math.floor(rand(0, nodeList.length))];
    if (!start) continue;
    let cur = start;
    const path = [cur];
    const steps = Math.floor(rand(4, 16));
    let dir = Math.floor(rand(0, 4));
    for (let s = 0; s < steps; s++) {
      if (Math.random() < 0.35) dir = (dir + (Math.random() < 0.5 ? 1 : 3)) % 4;
      const dx = [1, 0, -1, 0][dir], dy = [0, 1, 0, -1][dir];
      const next = nodes.get((cur.gx + dx) + ',' + (cur.gy + dy));
      if (!next) { dir = (dir + 2) % 4; continue; }
      path.push(next);
      cur = next;
    }
    if (path.length > 2) traces.push({ path, mix: Math.random() });
  }
  const pulseTraces = traces.slice(0, 16).map(tr => ({ ...tr, speed: rand(0.12, 0.26), phase: rand(0, 1) }));

  // "VOLT" chip, sized to its own text so the label is always legible -- computed
  // once (the label never changes), not re-measured every frame.
  const chipFontSize = Math.round(H * 0.026);
  ctx.font = `700 ${chipFontSize}px 'JetBrains Mono', monospace`;
  const chipLabel = 'VOLT';
  const chipPadX = W * 0.018, chipPadY = H * 0.012;
  const chipTextWidth = ctx.measureText(chipLabel).width;
  const chip = {
    w: chipTextWidth + chipPadX * 2,
    h: chipFontSize + chipPadY * 2,
    label: chipLabel,
    fontSize: chipFontSize,
  };
  chip.x = W * 0.5 - chip.w * 0.32;
  chip.y = H * 0.235;

  // Pointer-driven parallax: the head "faces" the cursor and pops toward it.
  // Plain closure variables, not React state -- mousemove must never trigger a
  // re-render, only nudge what the next animation frame draws.
  let mouseTX = 0, mouseTY = 0, curTX = 0, curTY = 0, hover = false;
  const stage = canvas.parentElement;
  const onMove = (ev) => {
    const rect = canvas.getBoundingClientRect();
    const nx = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
    const ny = ((ev.clientY - rect.top) / rect.height) * 2 - 1;
    mouseTX = Math.max(-1, Math.min(1, nx));
    mouseTY = Math.max(-1, Math.min(1, ny));
  };
  const onEnter = () => { hover = true; };
  const onLeave = () => { hover = false; mouseTX = 0; mouseTY = 0; };
  if (stage) {
    stage.addEventListener('mousemove', onMove);
    stage.addEventListener('mouseenter', onEnter);
    stage.addEventListener('mouseleave', onLeave);
  }

  const t0 = performance.now();
  let raf = null;
  const loop = (now) => {
    const t = (now - t0) / 1000;
    curTX += (mouseTX - curTX) * 0.07;
    curTY += (mouseTY - curTY) * 0.07;
    const hoverBoost = hover ? 1.18 : 1;
    ctx.clearRect(0, 0, W, H);

    ctx.save();
    const px = curTX * 10, py = curTY * 6;
    ctx.translate(px, py);
    const scale = 1 + (hover ? 0.015 : 0);
    ctx.translate(W / 2, H / 2);
    ctx.scale(scale, scale);
    ctx.translate(-W / 2, -H / 2);

    // Translucent fill -- the interior stays see-through, hologram-style. Blue-
    // dominant, matching the reference art's palette (amber stays a rare accent).
    headPath(ctx, W, H);
    const fillGrad = ctx.createLinearGradient(W * 0.3, H * 0.1, W * 0.7, H * 0.7);
    fillGrad.addColorStop(0, `rgba(${rgbB.r},${rgbB.g},${rgbB.b},0.10)`);
    fillGrad.addColorStop(0.5, `rgba(${rgbB.r},${rgbB.g},${rgbB.b},0.06)`);
    fillGrad.addColorStop(1, `rgba(${rgbA.r},${rgbA.g},${rgbA.b},0.04)`);
    ctx.fillStyle = fillGrad;
    ctx.fill();

    // Breathing outline -- blue, the dominant wireframe color.
    const breathe = 0.75 + 0.25 * Math.sin(t * 0.9);
    headPath(ctx, W, H);
    ctx.lineWidth = 1.3;
    ctx.strokeStyle = `rgba(${rgbB.r},${rgbB.g},${rgbB.b},0.9)`;
    ctx.shadowColor = `rgba(${rgbB.r},${rgbB.g},${rgbB.b},0.9)`;
    ctx.shadowBlur = (10 + 4 * breathe) * hoverBoost;
    ctx.stroke();

    // Faint facial contour underneath the circuitry.
    facialFeatures(ctx, W, H);
    ctx.lineWidth = 0.7;
    ctx.shadowBlur = 0;
    ctx.strokeStyle = `rgba(${rgbB.r},${rgbB.g},${rgbB.b},0.4)`;
    ctx.stroke();

    // Circuit traces + junction nodes -- blue-dominant, amber only as a rare
    // highlight thread. No per-line glow at this density (140 traces): it would
    // both wreck the frame rate and wash the dense lattice into a blur, so the
    // "glow" is opacity-only here and reserved for outline/chip/pulses below.
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.shadowBlur = 0;
    for (const tr of traces) {
      const rgb = tr.mix < 0.88 ? rgbB : rgbA;
      const path = tr.path;
      ctx.beginPath();
      ctx.moveTo(path[0].x, path[0].y);
      for (let i = 1; i < path.length; i++) ctx.lineTo(path[i].x, path[i].y);
      ctx.lineWidth = 0.6;
      ctx.strokeStyle = `rgba(${rgb.r},${rgb.g},${rgb.b},0.5)`;
      ctx.stroke();
      for (const p of path) {
        ctx.beginPath();
        ctx.fillStyle = `rgba(${rgb.r},${rgb.g},${rgb.b},0.75)`;
        ctx.arc(p.x, p.y, 0.9, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    // Traveling pulses along a subset of traces -- the circuitry "thinking".
    for (const pt of pulseTraces) {
      const tt = (pt.phase + t * pt.speed) % 1;
      const p = tracePoint(pt.path, tt);
      ctx.beginPath();
      ctx.fillStyle = '#fff8ec';
      ctx.shadowColor = `rgba(${rgbA.r},${rgbA.g},${rgbA.b},1)`;
      ctx.shadowBlur = 9 * hoverBoost;
      ctx.arc(p.x, p.y, 1.9, 0, Math.PI * 2);
      ctx.fill();
    }

    // "VOLT" chip, embedded above the temple -- the brand mark, amber against the
    // otherwise blue-dominant head.
    const chipGlow = 0.6 + 0.4 * Math.sin(t * 1.6);
    ctx.fillStyle = `rgba(${rgbA.r},${rgbA.g},${rgbA.b},0.18)`;
    ctx.strokeStyle = `rgba(${rgbA.r},${rgbA.g},${rgbA.b},0.95)`;
    ctx.lineWidth = 1;
    ctx.shadowColor = `rgba(${rgbA.r},${rgbA.g},${rgbA.b},1)`;
    ctx.shadowBlur = (8 + 4 * chipGlow) * hoverBoost;
    ctx.fillRect(chip.x, chip.y, chip.w, chip.h);
    ctx.strokeRect(chip.x, chip.y, chip.w, chip.h);
    ctx.font = `700 ${chip.fontSize}px 'JetBrains Mono', monospace`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = '#fff8ec';
    ctx.shadowBlur = (4 + 2 * chipGlow) * hoverBoost;
    ctx.fillText(chip.label, chip.x + chip.w / 2, chip.y + chip.h / 2 + 1);

    // Soft ambient core glow at the collar -- blend of both accents.
    const coreGlow = 0.6 + 0.4 * Math.sin(t * 1.6 + 1.2);
    const coreR = (5 + 2 * coreGlow) * hoverBoost;
    const gx = W * 0.5, gy = H * 0.6;
    const grad = ctx.createRadialGradient(gx, gy, 0, gx, gy, coreR * 3.2);
    grad.addColorStop(0, `rgba(${rgbB.r},${rgbB.g},${rgbB.b},0.7)`);
    grad.addColorStop(0.5, `rgba(${rgbA.r},${rgbA.g},${rgbA.b},0.35)`);
    grad.addColorStop(1, `rgba(${rgbA.r},${rgbA.g},${rgbA.b},0)`);
    ctx.shadowBlur = 0;
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(gx, gy, coreR * 3.2, 0, Math.PI * 2);
    ctx.fill();

    ctx.restore();
    raf = requestAnimationFrame(loop);
  };
  raf = requestAnimationFrame(loop);

  return () => {
    cancelAnimationFrame(raf);
    if (stage) {
      stage.removeEventListener('mousemove', onMove);
      stage.removeEventListener('mouseenter', onEnter);
      stage.removeEventListener('mouseleave', onLeave);
    }
  };
}

function CoreHero() {
  const canvasRef = useRef(null);

  useEffect(() => {
    if (!canvasRef.current) return;
    return initCore(canvasRef.current);
  }, []); // Empty deps: runs once on mount, regardless of how often the parent re-renders.

  return (
    <div className="panel hero-panel">
      <div className="hero-glow" style={{ background: `radial-gradient(circle at 38% 42%, ${ACCENT}26, transparent 62%), radial-gradient(circle at 64% 58%, ${ACCENT2}22, transparent 62%)` }} />
      <svg className="hero-rings" width="480" height="480" viewBox="0 0 480 480">
        <circle cx="240" cy="240" r="210" fill="none" stroke={ACCENT} strokeOpacity="0.16" strokeWidth="1" strokeDasharray="2 6" />
        <circle cx="240" cy="240" r="170" fill="none" stroke={ACCENT2} strokeOpacity="0.14" strokeWidth="1" />
      </svg>
      <canvas ref={canvasRef} className="hero-canvas" id="volt-particles" width="480" height="480" style={{ cursor: 'pointer' }} />
      <div className="hero-label">
        <div className="display hero-title">VOLT</div>
        <div className="mono hero-subtitle">NÚCLEO DE IA · v1.0</div>
      </div>
    </div>
  );
}

export default React.memo(CoreHero);
