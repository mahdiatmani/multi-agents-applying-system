import { useState, useEffect, useRef, Fragment } from 'react';
import './index.css';

const PlayIcon = () => (<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>);
const SquareIcon = () => (<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect></svg>);
const SearchIcon = () => (<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>);
const UsersIcon = () => (<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>);
const BriefcaseIcon = () => (<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="7" width="20" height="14" rx="2" ry="2"></rect><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"></path></svg>);
const BotIcon = () => (<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="logo-icon"><rect x="3" y="11" width="18" height="10" rx="2"></rect><circle cx="12" cy="5" r="2"></circle><path d="M12 7v4"></path><line x1="8" y1="16" x2="8" y2="16"></line><line x1="16" y1="16" x2="16" y2="16"></line></svg>);
const MailIcon = () => (<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path><polyline points="22,6 12,13 2,6"></polyline></svg>);
const SaveIcon = () => (<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path><polyline points="17 21 17 13 7 13 7 21"></polyline><polyline points="7 3 7 8 15 8"></polyline></svg>);
const UploadIcon = () => (<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>);
const KeyIcon = () => (<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"></path></svg>);
const XIcon = () => (<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>);
const ActivityIcon = () => (<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>);

const DEFAULT_LLM_MODEL = 'gpt-oss:120b-cloud';
const SETTINGS_STORAGE_PREFIX = 'applyBot:';

function usePersistedState(key, initialValue) {
  const storageKey = SETTINGS_STORAGE_PREFIX + key;
  const [value, setValue] = useState(() => {
    try {
      const raw = window.localStorage.getItem(storageKey);
      if (raw === null) return initialValue;
      return JSON.parse(raw);
    } catch {
      return initialValue;
    }
  });
  useEffect(() => {
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(value));
    } catch {
      // ignore quota / unavailable storage
    }
  }, [storageKey, value]);
  return [value, setValue];
}

function newId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
  return `id-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

const PIPELINE_STAGES = [
  { id: 'init',     label: 'Init',     hint: 'Open browser & login',     icon: <BotIcon /> },
  { id: 'search',   label: 'Search',   hint: 'Scrape the next item',      icon: <SearchIcon /> },
  { id: 'evaluate', label: 'Evaluate', hint: 'LLM scores the match',      icon: <ActivityIcon /> },
  { id: 'act',      label: 'Act',      hint: 'Apply, network, or draft',  icon: <BriefcaseIcon /> },
];

const ACTION_TO_STAGE = {
  PROCESSING: 'init',
  SEARCHED_JOB: 'search', SEARCHED_PERSON: 'search', SEARCHED_POST: 'search', SEARCHED_EMPTY: 'search',
  SKIP: 'evaluate',
  APPLY: 'act', APPLIED: 'act', APPLY_FAILED: 'act',
  NETWORK: 'act', NETWORKED: 'act', NETWORK_FAILED: 'act',
  DRAFT_EMAIL: 'act', DRAFTED_EMAIL: 'act',
  DRAFT_DM: 'act', DRAFTED_DM: 'act', DRAFT_FAILED: 'act',
  DRY_RUN_APPLY: 'act', DRY_RUN_NETWORK: 'act', DRY_RUN_EMAIL: 'act', DRY_RUN_DM: 'act',
  EXTERNAL_LEAD: 'act',
  DONE: 'init',
};

const ACTION_LABELS = {
  SEARCHED_JOB: 'Scraped job',
  SEARCHED_PERSON: 'Scraped profile',
  SEARCHED_POST: 'Scraped post',
  SEARCHED_EMPTY: 'No new results',
  SKIP: 'Skipped',
  APPLY: 'Applying',
  APPLIED: 'Applied',
  APPLY_FAILED: 'Apply failed',
  NETWORK: 'Sending connection',
  NETWORKED: 'Connected',
  NETWORK_FAILED: 'Connect failed',
  DRAFT_EMAIL: 'Drafting email',
  DRAFTED_EMAIL: 'Email drafted',
  DRAFT_DM: 'Drafting DM',
  DRAFTED_DM: 'DM drafted',
  DRAFT_FAILED: 'Draft failed',
  DRY_RUN_APPLY: 'Dry-run: would apply',
  DRY_RUN_NETWORK: 'Dry-run: would connect',
  DRY_RUN_EMAIL: 'Dry-run: would draft email',
  DRY_RUN_DM: 'Dry-run: would queue DM',
  EXTERNAL_LEAD: 'External ATS lead',
  ERROR: 'Error',
  DONE: 'Run complete',
  PROCESSING: 'Processing',
};

function PipelineDiagram({ stage }) {
  return (
    <div className="pipeline">
      {PIPELINE_STAGES.map((s, i) => (
        <Fragment key={s.id}>
          <div className={`pipeline-node ${stage === s.id ? 'active' : ''}`}>
            <div className="pipeline-node-icon">{s.icon}</div>
            <div className="pipeline-node-text">
              <div className="pipeline-label">{s.label}</div>
              <div className="pipeline-hint">{s.hint}</div>
            </div>
          </div>
          {i < PIPELINE_STAGES.length - 1 && <div className="pipeline-arrow" />}
        </Fragment>
      ))}
    </div>
  );
}

function StatsStrip({ stats }) {
  const items = [
    { label: 'Jobs scraped',     value: stats.jobsSearched ?? 0 },
    { label: 'Profiles/Posts',   value: stats.profilesFound ?? 0 },
    { label: 'Applied',          value: stats.applicationsSent ?? 0 },
    { label: 'Apply attempts',   value: stats.applicationsAttempted ?? 0 },
    { label: 'Drafts',           value: stats.draftsCreated ?? 0 },
  ];
  return (
    <div className="live-stats-strip">
      {items.map(it => (
        <div className="strip-stat" key={it.label}>
          <span>{it.label}</span>
          <strong>{it.value}</strong>
        </div>
      ))}
    </div>
  );
}

function HumanQuestionModal({ question, onSubmit, onSkip }) {
  const [text, setText] = useState('');
  const [saveForFuture, setSaveForFuture] = useState(true);
  const [picked, setPicked] = useState([]);
  useEffect(() => {
    setText('');
    setPicked([]);
    setSaveForFuture(true);
  }, [question?.id]);
  if (!question) return null;
  const isMulti = question.kind === 'checkbox-group';
  const hasOptions = Array.isArray(question.options) && question.options.length > 0;

  const togglePick = (opt) => {
    if (isMulti) {
      setPicked(prev => prev.includes(opt) ? prev.filter(x => x !== opt) : [...prev, opt]);
    } else {
      onSubmit(opt, saveForFuture);
    }
  };

  const submitFreeform = () => {
    const value = isMulti ? picked.join(', ') : text.trim();
    if (!value) return;
    onSubmit(value, saveForFuture);
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)',
      zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: '20px',
    }}>
      <div style={{
        background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '10px',
        padding: '22px 22px 18px', maxWidth: '520px', width: '100%', boxShadow: '0 20px 50px rgba(0,0,0,0.4)',
      }}>
        <h2 style={{ margin: '0 0 6px', fontSize: '1.15rem', color: 'var(--text-main)' }}>
          ✋ Need your input
        </h2>
        {question.context ? (
          <p style={{ margin: '0 0 12px', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            {question.context}
          </p>
        ) : null}
        <p style={{ margin: '0 0 14px', color: 'var(--text-main)' }}>{question.label}</p>

        {hasOptions ? (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '14px' }}>
            {question.options.map(opt => {
              const active = isMulti && picked.includes(opt);
              return (
                <button
                  key={opt}
                  type="button"
                  onClick={() => togglePick(opt)}
                  className="btn secondary"
                  style={{
                    margin: 0, padding: '0.45rem 0.8rem', fontSize: '0.85rem',
                    background: active ? 'var(--primary)' : undefined,
                    color: active ? '#fff' : undefined,
                  }}
                >
                  {opt}
                </button>
              );
            })}
          </div>
        ) : (
          <textarea
            value={text}
            onChange={e => setText(e.target.value)}
            placeholder="Type your answer..."
            rows={3}
            style={{
              width: '100%', padding: '0.6rem 0.8rem', borderRadius: '6px',
              border: '1px solid var(--border)', background: 'var(--background)',
              color: 'var(--text-main)', fontFamily: 'Inter', fontSize: '0.9rem',
              boxSizing: 'border-box', resize: 'vertical', marginBottom: '14px',
            }}
            autoFocus
          />
        )}

        <label className="checkbox-label" style={{ fontSize: '0.85rem' }}>
          <input
            type="checkbox"
            checked={saveForFuture}
            onChange={e => setSaveForFuture(e.target.checked)}
          />
          Save this answer for future jobs (adds to Form Q&A)
        </label>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '14px' }}>
          <button type="button" className="btn secondary" onClick={onSkip} style={{ margin: 0 }}>
            Skip (leave blank)
          </button>
          {(isMulti || !hasOptions) && (
            <button
              type="button"
              className="btn primary"
              onClick={submitFreeform}
              style={{ margin: 0 }}
              disabled={isMulti ? picked.length === 0 : !text.trim()}
            >
              Submit
            </button>
          )}
        </div>
      </div>
    </div>
  );
}


function TargetCard({ target }) {
  if (!target) {
    return (
      <div className="card target-card">
        <header><h3>Current Target</h3></header>
        <div className="empty">Waiting for the first scrape...</div>
      </div>
    );
  }
  const meta = [target.company, target.location].filter(Boolean).join(' · ');
  const summary = (target.summary || '').slice(0, 320);
  return (
    <div className="card target-card">
      <header>
        <h3>Current Target</h3>
        <span className={`kind-pill kind-${(target.kind || '').toLowerCase()}`}>{target.kind}</span>
      </header>
      <p className="target-title">{target.title || 'Untitled'}</p>
      {target.subtitle ? <p className="target-subtitle">{target.subtitle}</p> : null}
      {meta ? <p className="target-meta">{meta}</p> : null}
      {summary ? <p className="target-summary">{summary}{(target.summary || '').length > 320 ? '…' : ''}</p> : null}
      {target.url ? (
        <a className="target-link" href={target.url} target="_blank" rel="noreferrer">Open on LinkedIn ↗</a>
      ) : null}
    </div>
  );
}

function DecisionCard({ decision }) {
  if (!decision) {
    return (
      <div className="card decision-card">
        <header><h3>Last Decision</h3></header>
        <div className="empty">No evaluation has happened yet.</div>
      </div>
    );
  }
  const score = typeof decision.match_score === 'number' ? decision.match_score : 0;
  const scoreClass = score >= 75 ? 'score-good' : score >= 50 ? 'score-mid' : 'score-low';
  const act = (decision.recommended_action || 'PENDING').toUpperCase();
  return (
    <div className="card decision-card">
      <header><h3>Last Decision</h3></header>
      <div className="decision-row">
        <div className={`score-circle ${scoreClass}`}>
          <span className="score-num">{score}</span>
          <span className="score-denom">/100</span>
        </div>
        <span className={`action-badge action-${act.toLowerCase()}`}>{act}</span>
      </div>
      {decision.reasoning ? <p className="decision-reasoning">{decision.reasoning}</p> : null}
    </div>
  );
}

function TimelineFeed({ events }) {
  if (!events.length) {
    return (
      <div className="card timeline-card">
        <header><h3>Recent Actions</h3></header>
        <div className="empty">Events will appear here once the agent runs.</div>
      </div>
    );
  }
  return (
    <div className="card timeline-card">
      <header><h3>Recent Actions</h3></header>
      <ul className="timeline-list">
        {events.map((ev, i) => (
          <li key={i} className={`timeline-event ev-${(ev.action || 'info').toLowerCase()}`}>
            <span className="timeline-time">{ev.time}</span>
            <span className="timeline-action">{ACTION_LABELS[ev.action] || ev.action || 'Event'}</span>
            <span className="timeline-msg">{ev.message}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function LiveAgentView({ isRunning, logs, stats }) {
  const latestLog = logs[logs.length - 1];
  const action = latestLog?.action;
  const stage = !isRunning ? 'init' : (ACTION_TO_STAGE[action] || 'init');

  let currentTarget = null;
  let lastDecision = null;
  for (let i = logs.length - 1; i >= 0; i--) {
    const d = logs[i].detail;
    if (!d) continue;
    if (!currentTarget && (d.kind || d.title)) currentTarget = d;
    if (!lastDecision && (d.recommended_action || d.match_score !== undefined)) lastDecision = d;
    if (currentTarget && lastDecision) break;
  }

  const recent = logs.filter(l => l.action && l.action !== 'PROCESSING').slice(-12).reverse();

  const headerLabel = !isRunning
    ? 'Idle'
    : (ACTION_LABELS[action] || 'Processing');

  return (
    <div className="live-agent-view">
      <div className="live-header">
        <div className={`live-status-dot ${isRunning ? 'live' : 'idle'}`} />
        <div>
          <h2>{headerLabel}</h2>
          <p className="live-sub">{latestLog ? latestLog.message : 'Click Start Agent in the sidebar to begin.'}</p>
        </div>
      </div>

      <PipelineDiagram stage={stage} />

      <StatsStrip stats={stats} />

      <div className="live-grid">
        <TargetCard target={currentTarget} />
        <DecisionCard decision={lastDecision} />
      </div>

      <TimelineFeed events={recent} />
    </div>
  );
}

function upsertDetail(items, detail, action) {
  const id = detail.identifier || detail.url || `${detail.kind}-${newId()}`;
  const nextDetail = {
    ...detail,
    id,
    updatedAt: new Date().toLocaleTimeString(),
    lastAction: detail.recommended_action || action || '',
  };
  const existingIndex = items.findIndex(item => item.id === id);
  if (existingIndex === -1) return [...items, nextDetail];
  return items.map((item, index) => (
    index === existingIndex ? { ...item, ...nextDetail } : item
  ));
}

function Toast({ toast, onDismiss }) {
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(onDismiss, 3500);
    return () => clearTimeout(t);
  }, [toast, onDismiss]);
  if (!toast) return null;
  return (
    <div className={`toast toast-${toast.type || 'info'}`} role="status">
      {toast.message}
    </div>
  );
}

function StatCard({ icon, title, value, onClick }) {
  return (
    <button type="button" className="stat-card stat-card-button" onClick={onClick}>
      <h3>{icon} {title}</h3>
      <div className="value">{value}</div>
      <span className="stat-link">View details</span>
    </button>
  );
}

function DetailRow({ label, value }) {
  if (!value) return null;
  return (
    <div className="detail-row">
      <span>{label}</span>
      <p>{value}</p>
    </div>
  );
}

function DetailsPanel({ activeDetails, details, onClose }) {
  if (!activeDetails) return null;

  const isJobs = activeDetails === 'jobs';
  const items = isJobs ? details.jobs : details.profilesPosts;
  const title = isJobs ? 'Jobs Searched' : 'Profiles/Posts Scanned';

  return (
    <section className="details-panel" aria-label={`${title} details`}>
      <div className="details-panel-header">
        <div>
          <h2>{title}</h2>
          <p>{items.length} captured item{items.length === 1 ? '' : 's'}</p>
        </div>
        <button type="button" className="icon-button" onClick={onClose} aria-label="Close details">
          <XIcon />
        </button>
      </div>

      {items.length === 0 ? (
        <div className="empty-details">No details captured yet.</div>
      ) : (
        <div className="details-list">
          {items.map(item => (
            <article className="detail-item" key={item.id}>
              <div className="detail-item-header">
                <div>
                  <span className="detail-kind">{item.kind}</span>
                  <h3>{item.title}</h3>
                  {item.subtitle ? <p>{item.subtitle}</p> : null}
                </div>
                {item.match_score !== undefined ? (
                  <span className="match-score">{item.match_score}/100</span>
                ) : null}
              </div>
              <div className="detail-meta">
                {item.company ? <span>{item.company}</span> : null}
                {item.location ? <span>{item.location}</span> : null}
                {item.lastAction ? <span>{item.lastAction}</span> : null}
                {item.updatedAt ? <span>{item.updatedAt}</span> : null}
              </div>
              <DetailRow label="Summary" value={item.summary} />
              <DetailRow label="Reasoning" value={item.reasoning} />
              {item.url ? (
                <a className="detail-link" href={item.url} target="_blank" rel="noreferrer">
                  Open LinkedIn
                </a>
              ) : null}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

const PROFILE_FIELD_GROUPS = [
  {
    title: 'Personal',
    fields: [
      { key: 'first_name', label: 'First name' },
      { key: 'last_name',  label: 'Last name' },
      { key: 'email',      label: 'Email' },
      { key: 'phone',      label: 'Phone' },
      { key: 'city',       label: 'City' },
    ],
  },
  {
    title: 'Online presence',
    fields: [
      { key: 'linkedin',  label: 'LinkedIn URL' },
      { key: 'github',    label: 'GitHub URL' },
      { key: 'portfolio', label: 'Portfolio URL' },
    ],
  },
  {
    title: 'Application defaults',
    fields: [
      { key: 'years_exp',   label: 'Years of experience' },
      { key: 'authorized',  label: 'Authorized to work', note: 'Empty = auto: Yes when job is in Morocco, No abroad.' },
      { key: 'sponsorship', label: 'Need sponsorship',   note: 'Empty = auto: No when job is in Morocco, Yes abroad.' },
      { key: 'relocate',    label: 'Willing to relocate', placeholder: 'Yes / No' },
      { key: 'notice',      label: 'Notice period',       placeholder: '2 weeks' },
      { key: 'salary',      label: 'Expected salary',     placeholder: 'optional' },
    ],
  },
];

const SOURCE_BADGES = {
  override: { label: 'Manual',  cls: 'src-override' },
  env:      { label: '.env',    cls: 'src-env' },
  cv:       { label: 'CV',      cls: 'src-cv' },
  default:  { label: 'Default', cls: 'src-default' },
  missing:  { label: 'Missing', cls: 'src-missing' },
};

let profileReloadHandle = null;

function triggerProfileReload() {
  if (profileReloadHandle) profileReloadHandle();
}

function ProfileManager({ showToast, llmModel }) {
  const [profile, setProfile] = useState(null);
  const [overrides, setOverrides] = useState({});
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isParsing, setIsParsing] = useState(false);

  const load = () => {
    setIsLoading(true);
    fetch('/api/profile')
      .then(r => r.json())
      .then(data => {
        setProfile(data);
        const ov = {};
        for (const [k, cell] of Object.entries(data)) {
          ov[k] = cell.override || '';
        }
        setOverrides(ov);
      })
      .catch(() => showToast({ message: 'Failed to load profile.', type: 'error' }))
      .finally(() => setIsLoading(false));
  };

  useEffect(() => {
    load();
    profileReloadHandle = load;
    return () => { if (profileReloadHandle === load) profileReloadHandle = null; };
  }, []);

  const handleReparse = async () => {
    setIsParsing(true);
    try {
      const res = await fetch('/api/profile/parse', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ llm_model: llmModel }),
      });
      const data = await res.json();
      if (data.profile) {
        setProfile(data.profile);
        const ov = {};
        for (const [k, cell] of Object.entries(data.profile)) ov[k] = cell.override || '';
        setOverrides(ov);
      }
      const found = data.parsed_profile && Object.keys(data.parsed_profile).length;
      showToast({
        message: found ? `Parsed ${found} field(s) from CV.` : 'No new fields extracted.',
        type: found ? 'success' : 'info',
      });
    } catch {
      showToast({ message: 'CV re-parse failed.', type: 'error' });
    }
    setIsParsing(false);
  };

  const setField = (key, value) => setOverrides(prev => ({ ...prev, [key]: value }));

  const clearField = (key) => setOverrides(prev => ({ ...prev, [key]: '' }));

  const handleSave = async () => {
    setIsSaving(true);
    try {
      const res = await fetch('/api/profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ overrides }),
      });
      const data = await res.json();
      if (data.profile) {
        setProfile(data.profile);
        const ov = {};
        for (const [k, cell] of Object.entries(data.profile)) ov[k] = cell.override || '';
        setOverrides(ov);
      }
      showToast({ message: 'Profile saved.', type: 'success' });
    } catch {
      showToast({ message: 'Failed to save profile.', type: 'error' });
    }
    setIsSaving(false);
  };

  if (isLoading || !profile) {
    return <div className="profile-manager"><p>Loading profile...</p></div>;
  }

  return (
    <div className="profile-manager">
      <p className="profile-intro">
        Values used to auto-fill LinkedIn Easy Apply forms. Resolution order:
        <strong> Manual override → .env → CV.txt → Default</strong>.
        Leave a field blank to fall back to the next source.
      </p>

      {PROFILE_FIELD_GROUPS.map(group => (
        <section className="profile-group" key={group.title}>
          <h3>{group.title}</h3>
          {group.fields.map(f => {
            const cell = profile[f.key] || {};
            const badge = SOURCE_BADGES[cell.source] || SOURCE_BADGES.missing;
            const placeholder = cell.cv || cell.env || cell.default || f.placeholder || '';
            const hintParts = [];
            if (cell.cv) hintParts.push(`CV: ${cell.cv}`);
            if (cell.env) hintParts.push(`.env: ${cell.env}`);
            if (!cell.cv && !cell.env && cell.default) hintParts.push(`default: ${cell.default}`);
            return (
              <div className="profile-row" key={f.key}>
                <label htmlFor={`pf-${f.key}`}>
                  {f.label}
                  <span className={`source-badge ${badge.cls}`}>{badge.label}</span>
                </label>
                <div className="profile-input-row">
                  <input
                    id={`pf-${f.key}`}
                    type="text"
                    value={overrides[f.key] || ''}
                    placeholder={placeholder}
                    onChange={e => setField(f.key, e.target.value)}
                  />
                  {overrides[f.key] ? (
                    <button type="button" className="btn-link" onClick={() => clearField(f.key)}>
                      Reset
                    </button>
                  ) : null}
                </div>
                {hintParts.length > 0 ? <small className="profile-hint">{hintParts.join(' · ')}</small> : null}
                {f.note ? <small className="profile-hint">{f.note}</small> : null}
              </div>
            );
          })}
        </section>
      ))}

      <div className="profile-actions">
        <button className="btn primary" onClick={handleSave} disabled={isSaving}>
          <SaveIcon /> {isSaving ? 'Saving...' : 'Save Profile'}
        </button>
        <button className="btn secondary" onClick={handleReparse} disabled={isParsing || isSaving}>
          {isParsing ? 'Parsing with AI...' : 'Re-parse from CV'}
        </button>
        <button className="btn secondary" onClick={load} disabled={isSaving || isParsing}>
          Reload
        </button>
      </div>
    </div>
  );
}

function CVManager({ llmModel, showToast }) {
  const [cvText, setCvText] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [isUploading, setIsUploading] = useState(false);

  useEffect(() => {
    fetch('/api/cv')
      .then(res => res.json())
      .then(data => setCvText(data.content))
      .catch(err => console.error('Failed to load CV', err));
  }, []);

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await fetch('/api/cv', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: cvText }),
      });
      showToast({ message: 'CV saved.', type: 'success' });
    } catch {
      showToast({ message: 'Failed to save CV.', type: 'error' });
    }
    setIsSaving(false);
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    setIsUploading(true);
    const formData = new FormData();
    formData.append('file', file);
    formData.append('llm_model', llmModel);

    try {
      const res = await fetch('/api/upload-cv', { method: 'POST', body: formData });
      const data = await res.json();
      setCvText(data.content);
      const parsedCount = data.parsed_profile ? Object.keys(data.parsed_profile).length : 0;
      showToast({
        message: parsedCount ? `CV parsed. Auto-filled ${parsedCount} profile field(s).` : 'CV parsed.',
        type: 'success',
      });
      triggerProfileReload();
    } catch {
      showToast({ message: 'Failed to upload and parse CV.', type: 'error' });
    }
    setIsUploading(false);
  };

  return (
    <div className="cv-manager">
      <div className="cv-actions">
        <div style={{ display: 'flex', gap: '10px' }}>
          <button className="btn secondary upload-btn" style={{ margin: 0, padding: '0.6rem 1rem' }}>
            {isUploading ? 'Parsing with AI...' : <><UploadIcon /> Upload PDF CV</>}
            <input type="file" accept=".pdf" onChange={handleFileUpload} disabled={isUploading} />
          </button>
        </div>
        <button className="btn primary" onClick={handleSave} disabled={isSaving} style={{ margin: 0, padding: '0.6rem 1rem', width: 'auto' }}>
          <SaveIcon /> {isSaving ? 'Saving...' : 'Save CV'}
        </button>
      </div>
      <textarea
        className="cv-textarea"
        value={cvText}
        onChange={(e) => setCvText(e.target.value)}
        placeholder="Your CV content will appear here..."
      />
    </div>
  );
}

function MainContent({ isRunning, stats, details, activeDetails, setActiveDetails, logs, logsEndRef, currentTab, setCurrentTab, llmModel, showToast }) {
  return (
    <main className="main-content">
      <header>
        <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
          <h1>{
            currentTab === 'dashboard' ? 'Execution Dashboard'
            : currentTab === 'live'    ? 'Live Agent View'
            : currentTab === 'profile' ? 'Applicant Profile'
            : currentTab === 'qa'      ? 'Form Q&A Overrides'
            : 'CV Manager'
          }</h1>
          <div className="tabs">
            <button className={`tab ${currentTab === 'dashboard' ? 'active' : ''}`} onClick={() => setCurrentTab('dashboard')}>Dashboard</button>
            <button className={`tab ${currentTab === 'live' ? 'active' : ''}`}      onClick={() => setCurrentTab('live')}>Live View</button>
            <button className={`tab ${currentTab === 'profile' ? 'active' : ''}`}   onClick={() => setCurrentTab('profile')}>Profile</button>
            <button className={`tab ${currentTab === 'qa' ? 'active' : ''}`}        onClick={() => setCurrentTab('qa')}>Form Q&A</button>
            <button className={`tab ${currentTab === 'cv' ? 'active' : ''}`}        onClick={() => setCurrentTab('cv')}>CV Manager</button>
          </div>
        </div>
        <div className="status-badge" style={{ borderColor: isRunning ? 'var(--border)' : 'transparent' }}>
          <span className="status-dot" style={{ color: isRunning ? 'var(--success)' : 'var(--text-muted)' }}></span>
          <span>{isRunning ? 'Running' : 'Idle'}</span>
        </div>
      </header>

      {currentTab === 'dashboard' ? (
        <>
          <div className="stats-grid">
            <StatCard icon={<SearchIcon />} title="Jobs Searched" value={stats.jobsSearched}
              onClick={() => setActiveDetails(activeDetails === 'jobs' ? null : 'jobs')} />
            <StatCard icon={<UsersIcon />} title="Profiles/Posts Scanned" value={stats.profilesFound}
              onClick={() => setActiveDetails(activeDetails === 'profilesPosts' ? null : 'profilesPosts')} />
            <div className="stat-card">
              <h3><BriefcaseIcon /> Applications</h3>
              <div className="value">{stats.applicationsSent}</div>
            </div>
            <div className="stat-card">
              <h3><MailIcon /> Drafts Prepared</h3>
              <div className="value">{stats.draftsCreated}</div>
            </div>
          </div>

          <DetailsPanel
            activeDetails={activeDetails}
            details={details}
            onClose={() => setActiveDetails(null)}
          />

          <div className="terminal-wrapper">
            <div className="terminal-header">
              <div className="window-controls">
                <span></span><span></span><span></span>
              </div>
              <div className="terminal-title">agent-console.log</div>
            </div>
            <div className="terminal-body">
              {logs.map((log, idx) => (
                <div key={idx} className={`log-entry ${log.type}`}>
                  <span className="log-time">[{log.time}]</span>
                  <span className="log-msg">{log.message}</span>
                </div>
              ))}
              <div ref={logsEndRef} />
            </div>
          </div>
        </>
      ) : currentTab === 'live' ? (
        <LiveAgentView isRunning={isRunning} logs={logs} stats={stats} />
      ) : currentTab === 'profile' ? (
        <ProfileManager showToast={showToast} llmModel={llmModel} />
      ) : currentTab === 'qa' ? (
        <QAOverridesManager showToast={showToast} />
      ) : (
        <CVManager llmModel={llmModel} showToast={showToast} />
      )}
    </main>
  );
}

function QAOverridesManager({ showToast }) {
  const [entries, setEntries] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    fetch('/api/qa-overrides').then(r => r.json()).then(d => {
      setEntries(d.entries || []);
      setIsLoading(false);
    }).catch(() => setIsLoading(false));
  }, []);

  const addRow = () => setEntries([...entries, { pattern: '', answer: '' }]);
  const updateRow = (idx, key, val) => setEntries(entries.map((e, i) => i === idx ? { ...e, [key]: val } : e));
  const deleteRow = (idx) => setEntries(entries.filter((_, i) => i !== idx));

  const save = async () => {
    setIsSaving(true);
    try {
      const res = await fetch('/api/qa-overrides', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entries }),
      });
      const data = await res.json();
      if (data.status === 'success') {
        setEntries(data.entries || []);
        showToast({ message: 'Q&A overrides saved.', type: 'success' });
      } else {
        showToast({ message: data.message || 'Save failed', type: 'error' });
      }
    } catch (err) {
      showToast({ message: `Save failed: ${err.message}`, type: 'error' });
    }
    setIsSaving(false);
  };

  const resetDefaults = async () => {
    if (!window.confirm('Reset all Q&A overrides to defaults? Your custom entries will be lost.')) return;
    const res = await fetch('/api/qa-overrides/reset', { method: 'POST' });
    const data = await res.json();
    setEntries(data.entries || []);
    showToast({ message: 'Reset to defaults.', type: 'success' });
  };

  if (isLoading) return <div style={{ padding: '20px', color: 'var(--text-muted)' }}>Loading…</div>;

  return (
    <div style={{ padding: '20px', maxWidth: '900px' }}>
      <p style={{ color: 'var(--text-muted)', marginBottom: '20px', lineHeight: 1.5 }}>
        These regex patterns are matched against Easy Apply form labels (case-insensitive).
        First match wins. If the answer matches one of the field's options, that option is selected;
        otherwise the answer is typed verbatim. Resolution order:
        <strong> hardcoded heuristics → these overrides → LLM → safe Yes/No default</strong>.
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 80px', gap: '8px', marginBottom: '8px', fontWeight: 600, color: 'var(--text-muted)', fontSize: '0.85rem' }}>
        <div>Regex Pattern (matches the question label)</div>
        <div>Answer (typed or matched against options)</div>
        <div></div>
      </div>

      {entries.map((e, idx) => (
        <div key={idx} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 80px', gap: '8px', marginBottom: '6px' }}>
          <input
            type="text"
            value={e.pattern}
            onChange={ev => updateRow(idx, 'pattern', ev.target.value)}
            placeholder="e.g. start immediately|notice period"
            style={{ background: 'var(--background)', color: 'var(--text-main)', border: '1px solid var(--border)', padding: '0.5rem', borderRadius: '4px', fontFamily: 'monospace', fontSize: '0.85rem' }}
          />
          <input
            type="text"
            value={e.answer}
            onChange={ev => updateRow(idx, 'answer', ev.target.value)}
            placeholder="e.g. Yes"
            style={{ background: 'var(--background)', color: 'var(--text-main)', border: '1px solid var(--border)', padding: '0.5rem', borderRadius: '4px', fontSize: '0.85rem' }}
          />
          <button onClick={() => deleteRow(idx)} style={{ background: 'transparent', color: '#ef4444', border: '1px solid var(--border)', borderRadius: '4px', cursor: 'pointer' }}>Delete</button>
        </div>
      ))}

      <div style={{ display: 'flex', gap: '10px', marginTop: '16px' }}>
        <button className="btn secondary" onClick={addRow}>+ Add Row</button>
        <button className="btn primary" onClick={save} disabled={isSaving}>
          <SaveIcon /> {isSaving ? 'Saving…' : 'Save'}
        </button>
        <button className="btn secondary" onClick={resetDefaults}>Reset to defaults</button>
      </div>
    </div>
  );
}

export default function Root() {
  const [currentTab, setCurrentTab] = useState('dashboard');
  const [searchTypes, setSearchTypes] = usePersistedState('searchTypes', ['JOB']);
  const [role, setRole] = usePersistedState('role', 'AI');
  const [locations, setLocations] = usePersistedState('locations', ['Worldwide']);
  const [workplaceTypes, setWorkplaceTypes] = usePersistedState('workplaceTypes', ['Remote', 'Hybrid']);
  const [company, setCompany] = usePersistedState('company', 'Any');
  const [llmModel, setLlmModel] = usePersistedState('llmModel', DEFAULT_LLM_MODEL);
  const [allowOllamaCloud, setAllowOllamaCloud] = usePersistedState('allowOllamaCloud', false);
  const [headless, setHeadless] = usePersistedState('headless', true);
  const [dryRun, setDryRun] = usePersistedState('dryRun', false);
  const [verbose, setVerbose] = usePersistedState('verbose', false);
  const [availableModels, setAvailableModels] = useState([]);
  const [loginStatus, setLoginStatus] = useState(null);
  const [isLoggingIn, setIsLoggingIn] = useState(false);

  const [isRunning, setIsRunning] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [pendingQuestion, setPendingQuestion] = useState(null);
  const [logs, setLogs] = useState([{ message: 'System initialized. Awaiting commands.', type: 'system', time: new Date().toLocaleTimeString() }]);

  const [stats, setStats] = useState({ jobsSearched: 0, profilesFound: 0, applicationsSent: 0, draftsCreated: 0 });
  const [activityDetails, setActivityDetails] = useState({ jobs: [], profilesPosts: [] });
  const [activeDetails, setActiveDetails] = useState(null);
  const [toast, setToast] = useState(null);

  const eventSourceRef = useRef(null);
  const logsEndRef = useRef(null);

  const showToast = (t) => setToast(t);

  const addLog = (message, type = 'info', extras = {}) => {
    setLogs(prev => [...prev, { message, type, time: new Date().toLocaleTimeString(), ...extras }]);
  };

  const checkLoginStatus = () => {
    fetch('/api/login-status')
      .then(res => res.json())
      .then(data => setLoginStatus(data.logged_in))
      .catch(() => setLoginStatus(false));
  };

  useEffect(() => {
    fetch('/api/db')
      .then(res => res.json())
      .then(data => {
        if (data.stats) setStats(data.stats);
        if (data.history) setActivityDetails({ jobs: data.history.jobs || [], profilesPosts: data.history.profilesPosts || [] });
      })
      .catch(err => console.error('Failed to load db', err));

    fetch('/api/models')
      .then(res => res.json())
      .then(data => {
        if (data.models && data.models.length > 0) setAvailableModels(data.models);
        if (data.warning) addLog(data.warning, 'warning');
      })
      .catch(err => console.error('Failed to load models', err));

    checkLoginStatus();
  }, []);

  const handleClearDb = async () => {
    if (!window.confirm('Clear all stats and processed-job history? This cannot be undone.')) return;
    try {
      const res = await fetch('/api/db/reset', { method: 'POST' });
      const data = await res.json();
      if (data.status === 'success') {
        setStats({ jobsSearched: 0, profilesFound: 0, applicationsSent: 0, draftsCreated: 0 });
        setActivityDetails({ jobs: [], profilesPosts: [] });
        addLog(data.message || 'DB cleared.', 'success');
        showToast({ message: 'DB cleared.', type: 'success' });
      } else {
        addLog(data.message || 'DB reset failed.', 'error');
      }
    } catch (err) {
      addLog(`DB reset failed: ${err.message}`, 'error');
    }
  };

  const answerQuestion = async (answer, saveForFuture) => {
    if (!pendingQuestion) return;
    const qid = pendingQuestion.id;
    setPendingQuestion(null);
    try {
      await fetch('/api/answer-question', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: qid, answer, save_for_future: !!saveForFuture }),
      });
    } catch (err) {
      addLog(`Failed to submit answer: ${err.message}`, 'error');
    }
  };

  const skipQuestion = async () => {
    if (!pendingQuestion) return;
    const qid = pendingQuestion.id;
    setPendingQuestion(null);
    try {
      await fetch('/api/cancel-question', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: qid }),
      });
    } catch (err) {
      addLog(`Skip failed: ${err.message}`, 'error');
    }
  };

  const togglePause = async () => {
    const endpoint = isPaused ? '/api/resume' : '/api/pause';
    try {
      const res = await fetch(endpoint, { method: 'POST' });
      const data = await res.json();
      setIsPaused(!!data.paused);
      addLog(isPaused ? 'Resumed agent execution.' : 'Pause requested — running node will finish, then halt at next node.', 'system');
    } catch (err) {
      addLog(`Pause/resume failed: ${err.message}`, 'error');
    }
  };

  const handleCheckPending = async () => {
    addLog('Checking pending LinkedIn connections (this may take a minute)...', 'system');
    try {
      const res = await fetch('/api/check-pending', { method: 'POST' });
      const data = await res.json();
      if (data.status === 'success') {
        const r = data.result;
        addLog(`Pending sweep done — checked: ${r.checked}, accepted: ${r.accepted}, DM sent: ${r.dm_sent}, DM failed: ${r.dm_failed}, still pending: ${r.still_pending}`, 'success');
      } else {
        addLog(`Check pending failed: ${data.message}`, 'error');
      }
    } catch (err) {
      addLog(`Check pending failed: ${err.message}`, 'error');
    }
  };

  const handleManualLogin = async () => {
    setIsLoggingIn(true);
    addLog('Opening browser for LinkedIn login... Please log in and solve any CAPTCHAs.', 'system');
    try {
      const res = await fetch('/api/login', { method: 'POST' });
      const data = await res.json();
      if (data.status === 'success') {
        addLog(data.message, 'success');
        setLoginStatus(true);
      } else {
        addLog(data.message, 'error');
        setLoginStatus(false);
      }
    } catch (err) {
      addLog(`Login failed: ${err.message}`, 'error');
    }
    setIsLoggingIn(false);
    checkLoginStatus();
  };

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  const handleArrayChange = (setter, value) => {
    setter(prev => prev.includes(value) ? prev.filter(t => t !== value) : [...prev, value]);
  };

  const autoFillTarget = async () => {
    addLog(`Auto-analyzing CV to find best Role, Locations, and Workplace Types using ${llmModel}...`, 'system');
    try {
      const res = await fetch('/api/auto-target', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ llm_model: llmModel, allow_ollama_cloud: allowOllamaCloud }),
      });
      const data = await res.json();
      if (data.role) setRole(data.role);
      if (data.locations) setLocations(data.locations);
      if (data.workplace_types) setWorkplaceTypes(data.workplace_types);
      addLog(`Auto-filled Role: ${data.role} | Locations: ${data.locations?.join(', ')} | Types: ${data.workplace_types?.join(', ')}`, 'success');
    } catch (err) {
      addLog(`Failed to auto-fill target: ${err.message}`, 'error');
    }
  };

  const stopAgent = async () => {
    addLog('Stop requested — agent will halt at the next node boundary.', 'system');
    try {
      await fetch('/api/stop', { method: 'POST' });
    } catch (err) {
      addLog(`Stop API call failed: ${err.message}`, 'error');
    }
    // Keep the SSE feed open so the user sees the final STOPPED / DONE messages stream in.
    setIsPaused(false);
  };

  const startAgent = async () => {
    if (searchTypes.length === 0) {
      showToast({ message: 'Please select at least one agent mode.', type: 'error' });
      return;
    }

    addLog(`Initializing workflows [${searchTypes.join(', ')}] for ${role} in [${locations.join(', ')}] using ${llmModel}...`, 'system');
    setIsRunning(true);
    setIsPaused(false);

    try {
      const res = await fetch('/api/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          search_types: searchTypes,
          llm_model: llmModel,
          allow_ollama_cloud: allowOllamaCloud,
          role,
          locations,
          workplace_types: workplaceTypes,
          company,
          headless,
          dry_run: dryRun,
          verbose,
        }),
      });

      if (res.status === 409) {
        const data = await res.json();
        addLog(data.message || 'A run is already in progress.', 'warning');
        setIsRunning(false);
        return;
      }

      if (eventSourceRef.current) eventSourceRef.current.close();

      const source = new EventSource('/api/logs');
      eventSourceRef.current = source;

      source.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.action === 'PAUSED') setIsPaused(true);
        else if (data.action === 'RESUMED') setIsPaused(false);
        else if (data.action === 'ASK_HUMAN' && data.question) setPendingQuestion(data.question);
        else if (data.action === 'ANSWER_HUMAN') setPendingQuestion(prev => (prev && prev.id === data.question_id ? null : prev));
        addLog(data.message, data.type || 'info', { action: data.action });
        if (data.detail) {
          setActivityDetails(prev => {
            const bucket = data.detail.kind === 'Job' ? 'jobs' : 'profilesPosts';
            return { ...prev, [bucket]: upsertDetail(prev[bucket], data.detail, data.action) };
          });
        }

        if (data.action === 'SEARCHED_JOB' && data.detail) {
          setStats(s => ({ ...s, jobsSearched: s.jobsSearched + 1 }));
        } else if ((data.action === 'SEARCHED_PERSON' || data.action === 'SEARCHED_POST') && data.detail) {
          setStats(s => ({ ...s, profilesFound: s.profilesFound + 1 }));
        } else if (data.action === 'APPLIED') {
          setStats(s => ({ ...s, applicationsSent: s.applicationsSent + 1 }));
        } else if (data.action === 'DRAFTED_EMAIL' || data.action === 'DRAFTED_DM') {
          setStats(s => ({ ...s, draftsCreated: s.draftsCreated + 1 }));
        } else if (data.action === 'DONE') {
          source.close();
          eventSourceRef.current = null;
          setIsRunning(false);
        }
      };

      source.onerror = () => {
        // Browser auto-reconnects on transient errors; close to make termination final.
        source.close();
        eventSourceRef.current = null;
        addLog('Lost connection to stream.', 'error');
        setIsRunning(false);
      };

    } catch (err) {
      addLog(`Failed to start agent: ${err.message}`, 'error');
      stopAgent();
    }
  };

  return (
    <>
      {pendingQuestion && (
        <HumanQuestionModal
          question={pendingQuestion}
          onSubmit={answerQuestion}
          onSkip={skipQuestion}
        />
      )}
      <div className="sidebar" style={{ overflowY: 'auto' }}>
        <div className="brand">
          <BotIcon />
          <h2>Apply Agent</h2>
        </div>

        <div className="form-section">
          <div className="form-group">
            <label>Agent Modes</label>
            <div className="checkbox-group">
              {['JOB', 'PERSON', 'POST'].map(mode => (
                <label className="checkbox-label" key={mode}>
                  <input type="checkbox" checked={searchTypes.includes(mode)} onChange={() => handleArrayChange(setSearchTypes, mode)} />
                  {mode === 'JOB' ? 'Job Application' : mode === 'PERSON' ? 'Networking' : 'Post Scraping'}
                </label>
              ))}
            </div>
          </div>

          <div className="form-group">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <label>Target Role</label>
              <button onClick={autoFillTarget} style={{ background: 'none', border: 'none', color: 'var(--accent)', fontSize: '0.8rem', cursor: 'pointer', fontWeight: 500 }}>
                Auto Fill
              </button>
            </div>
            <input type="text" value={role} onChange={e => setRole(e.target.value)} placeholder="e.g. AI Engineer, Data Scientist" />
            <p style={{ margin: '6px 0 0', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              Comma-separate to rotate between roles (e.g. <code style={{ fontSize: '0.85em' }}>AI Engineer, Data Scientist</code>).
            </p>
          </div>

          <div className="form-group">
            <label>Workplace Type</label>
            <div className="checkbox-group">
              {['Remote', 'On-site', 'Hybrid'].map(type => (
                <label className="checkbox-label" key={type}>
                  <input type="checkbox" checked={workplaceTypes.includes(type)} onChange={() => handleArrayChange(setWorkplaceTypes, type)} />
                  {type}
                </label>
              ))}
            </div>
          </div>

          <div className="form-group">
            <label>Locations</label>
            <div className="checkbox-group">
              {['Worldwide', 'United States', 'Europe', 'United Kingdom', 'Canada', 'Morocco'].map(loc => (
                <label className="checkbox-label" key={loc}>
                  <input type="checkbox" checked={locations.includes(loc)} onChange={() => handleArrayChange(setLocations, loc)} />
                  {loc}
                </label>
              ))}
            </div>
          </div>

          <div className="form-group">
            <label>Target Company</label>
            <input type="text" value={company} onChange={e => setCompany(e.target.value)} placeholder="e.g. Any" />
          </div>

          <div className="form-group">
            <label className="checkbox-label">
              <input type="checkbox" checked={headless} onChange={(e) => setHeadless(e.target.checked)} />
              Run in Background (Headless)
            </label>
          </div>

          <div className="form-group">
            <label className="checkbox-label">
              <input type="checkbox" checked={allowOllamaCloud} onChange={(e) => setAllowOllamaCloud(e.target.checked)} />
              Allow Ollama cloud-tagged models
            </label>
          </div>

          <div className="form-group">
            <label className="checkbox-label" title="Score and decide actions but never submit, connect, or draft. Useful for tuning thresholds.">
              <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
              Dry run (preview only)
            </label>
          </div>

          <div className="form-group">
            <label className="checkbox-label" title="Forward [Resolve], [2ndPass], [Audit], [form_llm], [Apply] debug lines to this feed.">
              <input type="checkbox" checked={verbose} onChange={(e) => setVerbose(e.target.checked)} />
              Verbose logs (debug)
            </label>
          </div>

          <div className="form-group">
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              LinkedIn Session
              <span style={{
                display: 'inline-block', width: '8px', height: '8px', borderRadius: '50%',
                backgroundColor: loginStatus === null ? 'var(--text-muted)' : loginStatus ? 'var(--success)' : '#ef4444',
                boxShadow: loginStatus ? '0 0 6px var(--success)' : loginStatus === false ? '0 0 6px #ef4444' : 'none',
              }} />
              <span style={{ fontSize: '0.75rem', color: loginStatus ? 'var(--success)' : '#ef4444' }}>
                {loginStatus === null ? 'Checking...' : loginStatus ? 'Active' : 'Not logged in'}
              </span>
            </label>
            <button
              className="btn secondary"
              onClick={handleManualLogin}
              disabled={isLoggingIn}
              style={{ margin: 0, marginTop: '6px', padding: '0.5rem 0.8rem', fontSize: '0.85rem', width: '100%' }}
            >
              <KeyIcon /> {isLoggingIn ? 'Browser open — log in now...' : 'Login to LinkedIn'}
            </button>
          </div>

          <div className="form-group">
            <label htmlFor="ollama-model-input">Ollama model name</label>
            <input
              id="ollama-model-input"
              type="text"
              list="ollama-model-suggestions"
              autoComplete="off"
              spellCheck={false}
              value={llmModel}
              onChange={e => setLlmModel(e.target.value)}
              placeholder={`e.g. ${DEFAULT_LLM_MODEL}`}
              style={{
                backgroundColor: 'var(--background)', color: 'var(--text-main)',
                border: '1px solid var(--border)', padding: '0.6rem 0.8rem',
                borderRadius: '6px', fontSize: '0.9rem', fontFamily: 'Inter',
                width: '100%', boxSizing: 'border-box',
              }}
            />
            <datalist id="ollama-model-suggestions">
              {availableModels.map(m => (<option key={m} value={m} />))}
            </datalist>
            <p style={{ margin: '6px 0 0', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              Type the exact tag from <code style={{ fontSize: '0.85em' }}>ollama list</code>.
            </p>
          </div>

          <div className="form-group">
            <button
              className="btn secondary"
              onClick={handleCheckPending}
              disabled={isRunning}
              title="Visit each pending profile; if the connection was accepted, send the queued DM."
              style={{ margin: 0, padding: '0.5rem 0.8rem', fontSize: '0.85rem', width: '100%' }}
            >
              <MailIcon /> Check Pending Connections
            </button>
          </div>

          <div className="form-group">
            <button
              className="btn secondary"
              onClick={handleClearDb}
              disabled={isRunning}
              title="Resets stats and clears processed-job history (state/database.json and state/history.json)."
              style={{ margin: 0, padding: '0.5rem 0.8rem', fontSize: '0.85rem', width: '100%' }}
            >
              <XIcon /> Clear DB & History
            </button>
          </div>
        </div>

        <div className="controls">
          {!isRunning ? (
            <button className="btn primary" onClick={startAgent}>
              <PlayIcon /> Start Agent
            </button>
          ) : (
            <>
              <button
                className="btn secondary"
                onClick={togglePause}
                title={isPaused ? 'Resume execution' : 'Pause after the current node finishes'}
                style={{ marginRight: '8px' }}
              >
                {isPaused ? <><PlayIcon /> Resume</> : <><SquareIcon /> Pause</>}
              </button>
              <button className="btn secondary" onClick={stopAgent}>
                <SquareIcon /> Stop Execution
              </button>
            </>
          )}
          {isPaused && (
            <div style={{ marginTop: '6px', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
              Paused — current node will block at its next checkpoint.
            </div>
          )}
        </div>
      </div>

      <MainContent
        isRunning={isRunning}
        stats={stats}
        details={activityDetails}
        activeDetails={activeDetails}
        setActiveDetails={setActiveDetails}
        logs={logs}
        logsEndRef={logsEndRef}
        currentTab={currentTab}
        setCurrentTab={setCurrentTab}
        llmModel={llmModel}
        showToast={showToast}
      />
      <Toast toast={toast} onDismiss={() => setToast(null)} />
    </>
  );
}
