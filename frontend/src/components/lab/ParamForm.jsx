import { useState } from "react";
import { Link } from "react-router-dom";

export const GEOMETRY = new Set(["line", "polygon", "polygons", "points", "box"]);

function geoSummary(p, v) {
  if (p.type === "line") return v?.length === 2 ? "Line set" : "Not drawn";
  if (p.type === "box") return v?.length === 2 ? "Box set" : "Not drawn";
  if (p.type === "polygon") return v?.length >= 3 ? `${v.length} points` : v?.length ? `${v.length} points (need 3+)` : "Not drawn";
  if (p.type === "polygons") return v?.length ? `${v.length} shape${v.length > 1 ? "s" : ""}` : "None drawn";
  if (p.type === "points") return v?.length ? `${v.length} point${v.length > 1 ? "s" : ""}` : "No points";
  return "";
}

function MultiSelect({ p, value, onChange }) {
  const [q, setQ] = useState("");
  const sel = value || [];
  const many = (p.options || []).length > 12;
  const opts = (p.options || []).filter((o) => !sel.includes(o) && String(o).toLowerCase().includes(q.toLowerCase()));
  const toggle = (o) => onChange(sel.includes(o) ? sel.filter((x) => x !== o) : [...sel, o]);
  if (!many) {
    return (
      <div className="chipset">
        {(p.options || []).map((o) => (
          <button type="button" key={o} className={`chipbtn ${sel.includes(o) ? "on" : ""}`} aria-pressed={sel.includes(o)} onClick={() => toggle(o)}>{o}</button>
        ))}
      </div>
    );
  }
  return (
    <div className="ms">
      <div className="chipset">
        {sel.length === 0 && <span className="muted small">All</span>}
        {sel.map((o) => <button type="button" key={o} className="chipbtn on" onClick={() => toggle(o)} aria-label={`Remove ${o}`}>{o} ×</button>)}
      </div>
      <input id={`ms-${p.name}`} type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Add a class…" />
      {q && (
        <div className="ms-list">
          {opts.slice(0, 12).map((o) => <button type="button" key={o} onClick={() => { toggle(o); setQ(""); }}>{o}</button>)}
          {opts.length === 0 && <span className="muted small">No match</span>}
        </div>
      )}
    </div>
  );
}

function Field({ p, value, onChange, activeGeo, setActiveGeo, hasImage }) {
  const id = `p-${p.name}`;
  if (GEOMETRY.has(p.type)) {
    const active = activeGeo === p.name;
    return (
      <div className="field geo">
        <span>{p.label}</span>
        <div className="row between">
          <span className="muted small">{geoSummary(p, value)}</span>
          <div className="row gap8">
            <button type="button" className={`btn sm ${active ? "primary" : "ghost"}`} disabled={!hasImage}
              onClick={() => setActiveGeo(active ? null : p.name)}>{active ? "Done drawing" : "Draw on image"}</button>
            {value && (Array.isArray(value) ? value.length > 0 : true) && (
              <button type="button" className="btn ghost sm" onClick={() => onChange(Array.isArray(p.default) ? [] : null)}>Clear</button>
            )}
          </div>
        </div>
        {p.help && <small className="muted">{p.help}</small>}
        {!hasImage && <small className="muted">Add an input first, then draw on it.</small>}
      </div>
    );
  }
  if (p.type === "bool") {
    return (
      <label className="check" htmlFor={id}>
        <input id={id} type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />
        <span>{p.label}</span>
      </label>
    );
  }
  if (p.type === "number" || p.type === "int") {
    const step = p.step ?? (p.type === "int" ? 1 : 0.01);
    const useSlider = p.min !== undefined && p.max !== undefined && Math.abs(p.max - p.min) <= 1e4;
    return (
      <label className="field" htmlFor={id}>
        <span>{p.label}</span>
        <div className="numrow">
          {useSlider && <input type="range" min={p.min} max={p.max} step={step} value={value ?? p.min} aria-label={p.label}
            onChange={(e) => onChange(Number(e.target.value))} />}
          <input id={id} type="number" min={p.min} max={p.max} step={step} value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} />
        </div>
        {p.help && <small className="muted">{p.help}</small>}
      </label>
    );
  }
  if (p.type === "select") {
    return (
      <label className="field" htmlFor={id}>
        <span>{p.label}</span>
        <select id={id} value={String(value ?? "")} onChange={(e) => {
          const o = p.options.find((x) => String(x) === e.target.value);
          onChange(o ?? e.target.value);
        }}>
          {p.options.map((o) => <option key={String(o)} value={String(o)}>{String(o)}</option>)}
        </select>
        {p.help && <small className="muted">{p.help}</small>}
      </label>
    );
  }
  if (p.type === "multiselect") {
    return (
      <div className="field">
        <span>{p.label}</span>
        <MultiSelect p={p} value={value} onChange={onChange} />
        {p.help && <small className="muted">{p.help}</small>}
      </div>
    );
  }
  return (
    <label className="field" htmlFor={id}>
      <span>{p.label}</span>
      {p.type === "textarea"
        ? <textarea id={id} rows={5} value={value ?? ""} onChange={(e) => onChange(e.target.value)} dir="auto" />
        : <input id={id} type="text" value={value ?? ""} onChange={(e) => onChange(e.target.value)} dir="auto" />}
      {p.help && <small className="muted">{p.help}</small>}
    </label>
  );
}

export default function ParamForm({ tab, values, setValue, activeGeo, setActiveGeo, hasImage }) {
  const basic = tab.params.filter((p) => !p.advanced);
  const adv = tab.params.filter((p) => p.advanced);
  const field = (p) => <Field key={p.name} p={p} value={values[p.name]} onChange={(v) => setValue(p.name, v)}
    activeGeo={activeGeo} setActiveGeo={setActiveGeo} hasImage={hasImage} />;
  return (
    <div className="paramform">
      {tab.custom_task && (
        <label className="field" htmlFor="p-model">
          <span>Model</span>
          <select id="p-model" value={values.model || ""} onChange={(e) => setValue("model", e.target.value || null)}>
            <option value="">{tab.model_specs?.[0] ? `${tab.model_specs[0].name} (built-in)` : "Built-in"}</option>
            {tab.custom_models.map((m) => <option key={m.key} value={m.key}>{m.name}{m.public ? " (shared)" : ""}</option>)}
          </select>
          <small className="muted">Uses your own {tab.custom_task} weights if you pick them. <Link to="/models">Upload a model</Link></small>
        </label>
      )}
      {basic.map(field)}
      {adv.length > 0 && (
        <details className="advanced">
          <summary>Advanced settings</summary>
          {adv.map(field)}
        </details>
      )}
    </div>
  );
}
