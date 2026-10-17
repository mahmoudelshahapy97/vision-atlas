import { useEffect, useRef, useState } from "react";

/** Shows the input image with drawn geometry params; edits the active one. Coordinates are normalized 0..1. */
export default function CanvasEditor({ src, params, values, active, onChange }) {
  const [size, setSize] = useState({ w: 1000, h: 750 });
  const [drag, setDrag] = useState(null);
  const [draft, setDraft] = useState([]); // polygon being drawn (for "polygons")
  const svg = useRef(null);
  const ap = params.find((p) => p.name === active);

  useEffect(() => setDraft([]), [active, src]);

  const toNorm = (e) => {
    const r = svg.current.getBoundingClientRect();
    return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))];
  };
  const W = 1000;
  const H = (1000 * size.h) / size.w;
  const P = ([x, y]) => [x * W, y * H];
  const pts = (arr) => (arr || []).map((p) => P(p).join(",")).join(" ");

  function onClick(e) {
    if (!ap || ap.type === "box") return;
    const n = toNorm(e);
    const v = values[ap.name];
    if (ap.type === "line") onChange(ap.name, !v || v.length >= 2 ? [n] : [...v, n]);
    if (ap.type === "polygon") onChange(ap.name, [...(v || []), n]);
    if (ap.type === "points") onChange(ap.name, [...(v || []), [...n, e.shiftKey || e.altKey ? 0 : 1]]);
    if (ap.type === "polygons") setDraft((d) => [...d, n]);
  }
  function onContext(e) {
    if (ap?.type === "points") {
      e.preventDefault();
      const n = toNorm(e);
      onChange(ap.name, [...(values[ap.name] || []), [...n, 0]]);
    }
  }
  const down = (e) => { if (ap?.type === "box") { const n = toNorm(e); setDrag([n, n]); svg.current.setPointerCapture(e.pointerId); } };
  const move = (e) => { if (drag) setDrag([drag[0], toNorm(e)]); };
  const up = () => {
    if (drag) {
      const [a, b] = drag;
      if (Math.abs(a[0] - b[0]) > 0.01 && Math.abs(a[1] - b[1]) > 0.01) onChange(ap.name, [a, b]);
      setDrag(null);
    }
  };
  const finishPoly = () => {
    if (draft.length >= 3) onChange(ap.name, [...(values[ap.name] || []), draft]);
    setDraft([]);
  };
  const undo = () => {
    if (!ap) return;
    if (ap.type === "polygons") {
      if (draft.length) setDraft(draft.slice(0, -1));
      else onChange(ap.name, (values[ap.name] || []).slice(0, -1));
    } else if (Array.isArray(values[ap.name])) onChange(ap.name, values[ap.name].slice(0, -1));
  };

  const hint = !ap ? null : {
    line: "Click two points.", polygon: "Click to add corners.", polygons: "Click corners, then 'Finish shape'. Repeat for each.",
    points: "Click the object. Right-click or Shift-click marks background.", box: "Drag to draw a box.",
  }[ap.type];

  return (
    <div className={`canvas-editor ${ap ? "editing" : ""}`}>
      {ap && (
        <div className="editbar">
          <span><b>{ap.label}:</b> {hint}</span>
          <div className="row gap8">
            {ap.type === "polygons" && <button type="button" className="btn primary sm" onClick={finishPoly} disabled={draft.length < 3}>Finish shape</button>}
            {ap.type !== "box" && <button type="button" className="btn ghost sm" onClick={undo}>Undo</button>}
          </div>
        </div>
      )}
      <div className="stage">
        <img src={src} alt="Input" onLoad={(e) => setSize({ w: e.target.naturalWidth, h: e.target.naturalHeight })} draggable={false} />
        <svg ref={svg} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" onClick={onClick} onContextMenu={onContext}
          onPointerDown={down} onPointerMove={move} onPointerUp={up}>
          {params.map((p) => {
            const v = values[p.name];
            const on = p.name === active;
            const cls = on ? "geo-active" : "geo";
            if (!v || (Array.isArray(v) && !v.length)) return null;
            if (p.type === "line" && v.length) return (
              <g key={p.name} className={cls}>
                {v.length === 2 && <line x1={P(v[0])[0]} y1={P(v[0])[1]} x2={P(v[1])[0]} y2={P(v[1])[1]} />}
                {v.map((q, i) => <circle key={i} cx={P(q)[0]} cy={P(q)[1]} r="9" />)}
                {v.length === 2 && <text x={P(v[0])[0] + 12} y={P(v[0])[1] - 10}>A</text>}
                {v.length === 2 && <text x={P(v[1])[0] + 12} y={P(v[1])[1] - 10}>B</text>}
              </g>
            );
            if (p.type === "polygon") return (
              <g key={p.name} className={cls}><polygon points={pts(v)} />{v.map((q, i) => <circle key={i} cx={P(q)[0]} cy={P(q)[1]} r="7" />)}</g>
            );
            if (p.type === "polygons") return (
              <g key={p.name} className={cls}>{v.map((poly, i) => (
                <g key={i}><polygon points={pts(poly)} /><text x={P(poly[0])[0] + 6} y={P(poly[0])[1] + 22}>{i + 1}</text></g>
              ))}</g>
            );
            if (p.type === "points") return (
              <g key={p.name}>{v.map((q, i) => <circle key={i} cx={P(q)[0]} cy={P(q)[1]} r="10" className={q[2] ? "pt-pos" : "pt-neg"} />)}</g>
            );
            if (p.type === "box" && v.length === 2) {
              const [a, b] = [P(v[0]), P(v[1])];
              return <rect key={p.name} className={cls} x={Math.min(a[0], b[0])} y={Math.min(a[1], b[1])} width={Math.abs(a[0] - b[0])} height={Math.abs(a[1] - b[1])} />;
            }
            return null;
          })}
          {ap?.type === "polygons" && draft.length > 0 && (
            <g className="geo-active"><polyline points={pts(draft)} />{draft.map((q, i) => <circle key={i} cx={P(q)[0]} cy={P(q)[1]} r="7" />)}</g>
          )}
          {drag && (() => {
            const [a, b] = [P(drag[0]), P(drag[1])];
            return <rect className="geo-active" x={Math.min(a[0], b[0])} y={Math.min(a[1], b[1])} width={Math.abs(a[0] - b[0])} height={Math.abs(a[1] - b[1])} />;
          })()}
        </svg>
      </div>
    </div>
  );
}
