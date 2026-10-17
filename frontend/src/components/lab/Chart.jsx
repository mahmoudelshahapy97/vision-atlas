import { useMemo, useRef, useState } from "react";

const W = 640;
const H = 260;
const M = { l: 48, r: 16, t: 14, b: 40 };
const fmt = (v) => (typeof v !== "number" ? String(v) : Math.abs(v) >= 1000 ? v.toLocaleString(undefined, { maximumFractionDigits: 0 }) : +v.toFixed(Math.abs(v) < 10 ? 2 : 1));

function niceTicks(min, max, n = 5) {
  if (min === max) {
    max = min + 1;
  }
  const step0 = (max - min) / n;
  const p = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * p).find((s) => s >= step0) || step0;
  const start = Math.floor(min / step) * step;
  const ticks = [];
  for (let v = start; v < max + step * 0.999; v += step) ticks.push(+v.toFixed(10));
  return ticks;
}

/** Line, bar or scatter chart from a pipeline result: {type, title, x, series:[{name, values|points}], x_label, y_label} */
export default function Chart({ chart }) {
  const [hover, setHover] = useState(null);
  const ref = useRef(null);
  const { type, series = [] } = chart;
  const multi = series.length > 1;

  const geo = useMemo(() => {
    const iw = W - M.l - M.r;
    const ih = H - M.t - M.b;
    if (type === "scatter") {
      const pts = series.flatMap((s) => s.points || []);
      const xs = pts.map((p) => p[0]);
      const ys = pts.map((p) => p[1]);
      const xt = niceTicks(Math.min(...xs), Math.max(...xs));
      const yt = niceTicks(Math.min(...ys), Math.max(...ys));
      const sx = (v) => M.l + ((v - xt[0]) / (xt.at(-1) - xt[0])) * iw;
      const sy = (v) => M.t + ih - ((v - yt[0]) / (yt.at(-1) - yt[0])) * ih;
      return { xt, yt, sx, sy, iw, ih };
    }
    const x = chart.x || [];
    const vals = series.flatMap((s) => (s.values || []).filter((v) => v != null));
    const yt = niceTicks(Math.min(0, ...vals), Math.max(...vals, 1));
    const n = Math.max(1, x.length);
    const band = iw / n;
    const sx = type === "bar" ? (i) => M.l + band * i + band / 2 : (i) => M.l + (n === 1 ? iw / 2 : (i / (n - 1)) * iw);
    const sy = (v) => M.t + ih - ((v - yt[0]) / (yt.at(-1) - yt[0])) * ih;
    return { yt, sx, sy, band, n, iw, ih };
  }, [chart, type, series]);

  function onMove(e) {
    const svg = ref.current;
    if (!svg || type === "scatter") return;
    const rect = svg.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * W;
    const n = geo.n;
    let i;
    if (type === "bar") i = Math.floor((px - M.l) / geo.band);
    else i = Math.round(((px - M.l) / geo.iw) * (n - 1));
    if (i >= 0 && i < n) setHover({ i, x: geo.sx(i) });
    else setHover(null);
  }

  const xLabels = chart.x || [];
  const every = Math.max(1, Math.ceil(xLabels.length / 8));

  return (
    <figure className="chart">
      <figcaption className="chart-title">{chart.title}</figcaption>
      {multi && (
        <div className="chart-legend">
          {series.map((s, i) => (
            <span key={s.name}><i style={{ background: `var(--series-${(i % 8) + 1})` }} />{s.name}</span>
          ))}
        </div>
      )}
      <div className="chart-wrap">
        <svg ref={ref} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={chart.title} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
          {geo.yt.map((v) => (
            <g key={v}>
              <line x1={M.l} x2={W - M.r} y1={geo.sy(v)} y2={geo.sy(v)} className="grid" />
              <text x={M.l - 6} y={geo.sy(v) + 4} textAnchor="end" className="tick">{fmt(v)}</text>
            </g>
          ))}
          {type === "scatter" && geo.xt.map((v) => (
            <text key={v} x={geo.sx(v)} y={H - M.b + 16} textAnchor="middle" className="tick">{fmt(v)}</text>
          ))}
          {type !== "scatter" && xLabels.map((l, i) => (i % every === 0 ? (
            <text key={i} x={geo.sx(i)} y={H - M.b + 16} textAnchor="middle" className="tick">{String(l).slice(0, 12)}</text>
          ) : null))}
          {chart.x_label && <text x={M.l + geo.iw / 2} y={H - 4} textAnchor="middle" className="axis-label">{chart.x_label}</text>}

          {type === "line" && series.map((s, si) => {
            const pts = (s.values || []).map((v, i) => (v == null ? null : [geo.sx(i), geo.sy(v)]));
            const d = pts.reduce((acc, p, i) => (p ? acc + (acc && pts[i - 1] ? "L" : "M") + p[0].toFixed(1) + "," + p[1].toFixed(1) : acc), "");
            return <path key={s.name} d={d} fill="none" stroke={`var(--series-${(si % 8) + 1})`} strokeWidth="2" strokeLinejoin="round" />;
          })}
          {type === "bar" && series.map((s, si) => {
            const bw = Math.max(2, (geo.band - 4) / series.length - 2);
            return (s.values || []).map((v, i) => {
              if (v == null) return null;
              const x = geo.sx(i) - (bw * series.length) / 2 + si * (bw + 2);
              const y = geo.sy(Math.max(v, 0));
              const h = Math.abs(geo.sy(v) - geo.sy(0));
              return <rect key={`${si}-${i}`} x={x} y={y} width={bw} height={Math.max(1, h)} rx="3" fill={`var(--series-${(si % 8) + 1})`}
                opacity={hover && hover.i !== i ? 0.55 : 1} />;
            });
          })}
          {type === "scatter" && series.map((s, si) => (s.points || []).map((p, i) => (
            <circle key={`${si}-${i}`} cx={geo.sx(p[0])} cy={geo.sy(p[1])} r="5" fill={`var(--series-${(si % 8) + 1})`}
              stroke="var(--surface)" strokeWidth="2"
              onMouseEnter={() => setHover({ label: p[2] ?? `${fmt(p[0])}, ${fmt(p[1])}`, series: s.name, cx: geo.sx(p[0]), cy: geo.sy(p[1]) })}
              onMouseLeave={() => setHover(null)} />
          )))}
          {hover && type === "line" && <line x1={hover.x} x2={hover.x} y1={M.t} y2={H - M.b} className="crosshair" />}
        </svg>
        {hover && type !== "scatter" && (
          <div className="chart-tip" style={{ left: `${(hover.x / W) * 100}%` }}>
            <b>{String(xLabels[hover.i])}{chart.x_label ? ` ${chart.x_label.replace(/\(.*\)/, "").trim()}` : ""}</b>
            {series.map((s, si) => (
              <span key={s.name}><i style={{ background: `var(--series-${(si % 8) + 1})` }} />{s.name}: {fmt(s.values?.[hover.i])}</span>
            ))}
          </div>
        )}
        {hover && type === "scatter" && (
          <div className="chart-tip" style={{ left: `${(hover.cx / W) * 100}%`, top: `${(hover.cy / H) * 100}%` }}>
            <b>{hover.label}</b><span>{hover.series}</span>
          </div>
        )}
      </div>
      {chart.y_label && <p className="chart-ylabel">{chart.y_label}</p>}
    </figure>
  );
}
