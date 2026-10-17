import { LEVELS } from "../utils/constants";
import { pad } from "../utils/format";
import { LevelBars, Star, StatusPill, SupportBadge } from "./StatusChips";

export default function ProjectCard({ project: p, onOpen, showStatus }) {
  return (
    <button className="card" onClick={() => onOpen(p.id)} aria-label={`Project ${p.id}: ${p.title}`}>
      <span className="corners" aria-hidden="true"></span>
      <span className="row1">
        <span className="tag">#{pad(p.id)} · {p.task_type.code.toUpperCase()}</span>
        <span className="lvlwrap">{LEVELS[p.level]}<LevelBars level={p.level} /></span>
      </span>
      <span className="row between"><span className="dom">{p.domain.name}</span>{p.lab && <SupportBadge level={p.lab.support} compact />}</span>
      <span className="ct">{p.title}</span>
      <span className="cd">{p.description}</span>
      <span className="chips">
        {p.technologies.slice(0, 3).map((t) => <span className="chip" key={t}>{t}</span>)}
        {p.technologies.length > 3 && <span className="chip">+{p.technologies.length - 3}</span>}
      </span>
      <span className="cfoot">
        {showStatus ? <StatusPill status={p.progress?.status} /> : <span>{p.task_type.metric}</span>}
        {p.is_pick ? <span className="pick"><Star />Top pick</span> : showStatus ? <span>{p.task_type.metric}</span> : null}
      </span>
    </button>
  );
}
