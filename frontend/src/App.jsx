import { useState, useEffect, useRef, Fragment, useCallback } from 'react';
import './index.css';

const PlayIcon = () => (<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>);
const SquareIcon = () => (<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect></svg>);
const SearchIcon = () => (<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>);
const UsersIcon = () => (<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>);
const BriefcaseIcon = () => (<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="7" width="20" height="14" rx="2" ry="2"></rect><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"></path></svg>);
const BotIcon = () => (<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="logo-icon"><rect x="3" y="11" width="18" height="10" rx="2"></rect><circle cx="12" cy="5" r="2"></circle><path d="M12 7v4"></path><line x1="8" y1="16" x2="8" y2="16"></line><line x1="16" y1="16" x2="16" y2="16"></line></svg>);
const MailIcon = () => (<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path><polyline points="22,6 12,13 2,6"></polyline></svg>);
const FileTextIcon = () => (<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>);
const SaveIcon = () => (<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path><polyline points="17 21 17 13 7 13 7 21"></polyline><polyline points="7 3 7 8 15 8"></polyline></svg>);
const UploadIcon = () => (<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>);
const KeyIcon = () => (<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"></path></svg>);
const XIcon = () => (<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>);
const ActivityIcon = () => (<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>);

const DEFAULT_LLM_MODEL = 'gpt-oss:120b-cloud';
const SETTINGS_STORAGE_PREFIX = 'applyBot:';

// Lightweight global event channel for backend-offline signaling.
const backendStatus = {
  online: true,
  listeners: new Set(),
  set(online) {
    if (this.online === online) return;
    this.online = online;
    this.listeners.forEach(fn => { try { fn(online); } catch {} });
  },
  subscribe(fn) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  },
};

// fetch wrapper: turns ECONNREFUSED (Vite's 503 {error:'backend_offline'}) and TypeError
// (browser network failure) into a uniform thrown error AND flips backendStatus.
async function apiFetch(input, init) {
  try {
    const res = await fetch(input, init);
    if (res.status === 503) {
      // Vite proxy says backend is down. Peek at body to confirm.
      try {
        const clone = res.clone();
        const data = await clone.json();
        if (data && data.error === 'backend_offline') {
          backendStatus.set(false);
          throw new Error('backend_offline');
        }
      } catch (e) {
        if (e.message === 'backend_offline') throw e;
      }
    }
    backendStatus.set(true);
    return res;
  } catch (err) {
    // TypeError / network refused (when not running via Vite dev — e.g. served from FastAPI).
    if (err && (err.name === 'TypeError' || err.message === 'backend_offline' || err.message === 'Failed to fetch')) {
      backendStatus.set(false);
    }
    throw err;
  }
}

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
  EXTERNAL_LINK: 'act', EXTERNAL_LINK_RECORDED: 'act', EXTERNAL_LINK_FAILED: 'act',
  DRY_RUN_APPLY: 'act', DRY_RUN_NETWORK: 'act', DRY_RUN_EMAIL: 'act', DRY_RUN_DM: 'act', DRY_RUN_LINK: 'act',
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
  EXTERNAL_LINK: 'Apply link',
  EXTERNAL_LINK_RECORDED: 'Apply link recorded',
  EXTERNAL_LINK_FAILED: 'Apply link failed',
  DRY_RUN_LINK: 'Dry-run: would record link',
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
    { label: 'Posts',            value: stats.postsFound ?? 0 },
    { label: 'Profiles',         value: stats.profilesFound ?? 0 },
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
  const [prevId, setPrevId] = useState(question?.id);

  if (question?.id !== prevId) {
    setPrevId(question?.id);
    setText('');
    setPicked([]);
    setSaveForFuture(true);
  }
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
  const isPost = target.kind === 'Post';
  const rawSummary = target.summary || '';
  // For posts we show the entire body (so the user can read what was scraped).
  // For jobs/profiles we keep the previous 320-char preview to stay compact.
  const summary = isPost ? rawSummary : rawSummary.slice(0, 320);
  const summaryTruncated = !isPost && rawSummary.length > 320;
  return (
    <div className="card target-card">
      <header>
        <h3>Current Target</h3>
        <span className={`kind-pill kind-${(target.kind || '').toLowerCase()}`}>{target.kind}</span>
      </header>
      <p className="target-title">
        {isPost ? <span className="target-post-author-label">Posted by </span> : null}
        {target.title || 'Untitled'}
      </p>
      {target.subtitle ? <p className="target-subtitle">{target.subtitle}</p> : null}
      {meta ? <p className="target-meta">{meta}</p> : null}
      {summary ? (
        <p className={`target-summary${isPost ? ' target-summary-post' : ''}`}>
          {summary}{summaryTruncated ? '…' : ''}
        </p>
      ) : null}
      {isPost && (target.primary_email || target.attached_job_url) ? (
        <div className="target-signals" style={{
          display: 'flex', gap: '8px', flexWrap: 'wrap',
          marginTop: '8px', fontSize: '0.8rem',
        }}>
          {target.primary_email ? (
            <span style={{
              background: 'rgba(16,185,129,0.15)', color: '#10b981',
              padding: '2px 8px', borderRadius: '4px', fontWeight: 600,
            }}>
              ✉ {target.primary_email}
            </span>
          ) : null}
          {target.attached_job_url ? (
            <a href={target.attached_job_url} target="_blank" rel="noreferrer" style={{
              background: 'rgba(99,102,241,0.15)', color: '#a5b4fc',
              padding: '2px 8px', borderRadius: '4px', textDecoration: 'none',
            }}>
              📎 attached job ↗
            </a>
          ) : null}
        </div>
      ) : null}
      <div style={{ display: 'flex', gap: '12px', marginTop: '8px', flexWrap: 'wrap' }}>
        {target.url ? (
          <a className="target-link" href={target.url} target="_blank" rel="noreferrer">Open on LinkedIn ↗</a>
        ) : null}
        {isPost && target.author_url && target.author_url !== target.url ? (
          <a className="target-link" href={target.author_url} target="_blank" rel="noreferrer">Open author profile ↗</a>
        ) : null}
        {isPost && target.post_url && target.post_url !== target.url ? (
          <a className="target-link" href={target.post_url} target="_blank" rel="noreferrer">Permalink ↗</a>
        ) : null}
      </div>
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
  let lastPostBatch = null;
  for (let i = logs.length - 1; i >= 0; i--) {
    const log = logs[i];
    if (!lastPostBatch && log.post_batch) lastPostBatch = log.post_batch;
    const d = log.detail;
    if (d) {
      if (!currentTarget && (d.kind || d.title)) currentTarget = d;
      if (!lastDecision && (d.recommended_action || d.match_score !== undefined)) lastDecision = d;
    }
    if (currentTarget && lastDecision && lastPostBatch) break;
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

      {lastPostBatch ? <PostBatchStrip batch={lastPostBatch} /> : null}

      <StatsStrip stats={stats} />

      <div className="live-grid">
        <TargetCard target={currentTarget} />
        <DecisionCard decision={lastDecision} />
      </div>

      <TimelineFeed events={recent} />
    </div>
  );
}

function PostBatchStrip({ batch }) {
  const depth = batch.queue_depth ?? 0;
  const role = batch.batch_role || '';
  return (
    <div className="live-stats-strip" style={{ marginTop: '8px' }}>
      <div className="strip-stat">
        <span>Post batch</span>
        <strong>{depth} queued</strong>
      </div>
      {role ? (
        <div className="strip-stat">
          <span>Scraped for</span>
          <strong>hiring {role}</strong>
        </div>
      ) : null}
      <div className="strip-stat" style={{ flex: 1, minWidth: '120px' }}>
        <span>Flow</span>
        <strong style={{ fontSize: '0.78rem', color: 'var(--text-muted)', fontWeight: 400 }}>
          scrape feed → queue → evaluate one-by-one → apply / email / DM
        </strong>
      </div>
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

  const PANEL_META = {
    jobs:     { title: 'Jobs Searched' },
    posts:    { title: 'Posts Scanned' },
    profiles: { title: 'Profiles Scanned' },
  };
  const items = details[activeDetails] || [];
  const title = (PANEL_META[activeDetails] || {}).title || 'Details';

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

  const load = useCallback(() => {
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
  }, [showToast]);

  useEffect(() => {
    load();
    profileReloadHandle = () => { setIsLoading(true); load(); };
    return () => { profileReloadHandle = null; };
  }, [load]);

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
            : currentTab === 'cv'      ? 'CV Manager'
            : currentTab === 'outreach' ? 'Outreach Tracker'
            : 'External Leads'
          }</h1>
          <div className="tabs">
            <button className={`tab ${currentTab === 'dashboard' ? 'active' : ''}`} onClick={() => setCurrentTab('dashboard')}>Dashboard</button>
            <button className={`tab ${currentTab === 'live' ? 'active' : ''}`}      onClick={() => setCurrentTab('live')}>Live View</button>
            <button className={`tab ${currentTab === 'profile' ? 'active' : ''}`}   onClick={() => setCurrentTab('profile')}>Profile</button>
            <button className={`tab ${currentTab === 'qa' ? 'active' : ''}`}        onClick={() => setCurrentTab('qa')}>Form Q&A</button>
            <button className={`tab ${currentTab === 'cv' ? 'active' : ''}`}        onClick={() => setCurrentTab('cv')}>CV Manager</button>
            <button className={`tab ${currentTab === 'outreach' ? 'active' : ''}`}  onClick={() => setCurrentTab('outreach')}>Outreach</button>
            <button className={`tab ${currentTab === 'leads' ? 'active' : ''}`}     onClick={() => setCurrentTab('leads')}>Leads</button>
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
            <StatCard icon={<FileTextIcon />} title="Posts Scanned" value={stats.postsFound}
              onClick={() => setActiveDetails(activeDetails === 'posts' ? null : 'posts')} />
            <StatCard icon={<UsersIcon />} title="Profiles Scanned" value={stats.profilesFound}
              onClick={() => setActiveDetails(activeDetails === 'profiles' ? null : 'profiles')} />
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
      ) : currentTab === 'cv' ? (
        <CVManager llmModel={llmModel} showToast={showToast} />
      ) : currentTab === 'outreach' ? (
        <OutreachManager showToast={showToast} />
      ) : (
        <ExternalLeadsManager showToast={showToast} />
      )}
    </main>
  );
}


function OutreachManager({ showToast }) {
  const [emails, setEmails] = useState({ items: [], stats: {} });
  const [links, setLinks] = useState({ items: [], stats: {} });
  const [connections, setConnections] = useState({ items: [], stats: {} });
  const [gmailAuthed, setGmailAuthed] = useState(true);
  const [section, setSection] = useState('emails');
  const [loading, setLoading] = useState(true);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const r = await fetch('/api/outreach');
      const data = await r.json();
      setGmailAuthed(data.gmail_authed !== false);
      setEmails(data.emails || { items: [], stats: {} });
      setLinks(data.links || { items: [], stats: {} });
      setConnections(data.connections || { items: [], stats: {} });
    } catch (err) {
      showToast?.({ message: `Failed to load outreach: ${err.message}`, type: 'error' });
    }
    setLoading(false);
  };

  useEffect(() => { fetchAll(); }, []);

  const setEmailStatus = async (item, status) => {
    const identifier = item.to_email || item.post_url;
    try {
      await fetch('/api/outreach/emails/status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ identifier, status }),
      });
      await fetchAll();
    } catch (err) {
      showToast?.({ message: `Status update failed: ${err.message}`, type: 'error' });
    }
  };

  const removeEmail = async (item) => {
    if (!window.confirm(`Remove draft to ${item.to_email}?`)) return;
    const identifier = item.to_email || item.post_url;
    try {
      await fetch('/api/outreach/emails/remove', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ identifier }),
      });
      await fetchAll();
    } catch (err) {
      showToast?.({ message: `Remove failed: ${err.message}`, type: 'error' });
    }
  };

  const clearEmails = async () => {
    if (!emails.items.length) return;
    if (!window.confirm(`Delete all ${emails.items.length} drafted email(s)? Gmail drafts will NOT be deleted — only the local tracking record.`)) return;
    try {
      await fetch('/api/outreach/emails/clear', { method: 'POST' });
      await fetchAll();
      showToast?.({ message: 'Email tracking cleared.', type: 'success' });
    } catch (err) {
      showToast?.({ message: `Clear failed: ${err.message}`, type: 'error' });
    }
  };

  const setLinkStatus = async (item, status) => {
    const identifier = item.apply_url || item.post_url;
    try {
      await fetch('/api/outreach/links/status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ identifier, status }),
      });
      await fetchAll();
    } catch (err) {
      showToast?.({ message: `Status update failed: ${err.message}`, type: 'error' });
    }
  };

  const removeLink = async (item) => {
    if (!window.confirm(`Remove apply-link for ${item.post_author || 'this post'}?`)) return;
    const identifier = item.apply_url || item.post_url;
    try {
      await fetch('/api/outreach/links/remove', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ identifier }),
      });
      await fetchAll();
    } catch (err) {
      showToast?.({ message: `Remove failed: ${err.message}`, type: 'error' });
    }
  };

  const clearLinks = async () => {
    if (!links.items.length) return;
    if (!window.confirm(`Delete all ${links.items.length} apply-link record(s)?`)) return;
    try {
      await fetch('/api/outreach/links/clear', { method: 'POST' });
      await fetchAll();
      showToast?.({ message: 'Apply-link tracking cleared.', type: 'success' });
    } catch (err) {
      showToast?.({ message: `Clear failed: ${err.message}`, type: 'error' });
    }
  };

  const setConnStatus = async (item, status) => {
    try {
      await fetch('/api/outreach/connections/status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile_url: item.profile_url, status }),
      });
      await fetchAll();
    } catch (err) {
      showToast?.({ message: `Status update failed: ${err.message}`, type: 'error' });
    }
  };

  const emailStats = emails.stats || {};
  const linkStats = links.stats || {};
  const connStats = connections.stats || {};

  return (
    <div className="card" style={{ padding: '1rem', marginTop: '1rem' }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.8rem', flexWrap: 'wrap', gap: '8px' }}>
        <div>
          <h3 style={{ margin: 0 }}>Outreach Tracker</h3>
          <p style={{ margin: '4px 0 0', color: 'var(--text-muted)', fontSize: '0.82rem' }}>
            Every email draft + every connection request + every queued/sent DM the bot has produced.
          </p>
        </div>
        <button className="btn secondary" onClick={fetchAll} style={{ margin: 0, padding: '0.4rem 0.8rem', fontSize: '0.85rem' }}>Refresh</button>
      </header>

      {!gmailAuthed ? (
        <div style={{
          background: 'rgba(239, 68, 68, 0.12)', border: '1px solid #ef4444',
          color: '#fecaca', padding: '10px 12px', borderRadius: '6px',
          marginBottom: '12px', fontSize: '0.85rem',
        }}>
          <strong>⚠ Gmail not connected</strong> — the bot will still <em>decide</em> to draft emails
          based on hiring posts, and the bodies will appear here under "Emails drafted" with status
          <code style={{ background: 'rgba(0,0,0,0.25)', padding: '0 6px', borderRadius: '3px', margin: '0 4px' }}>gmail_unauth</code>
          so you can copy them. To get Gmail to actually create the drafts, run
          <code style={{ background: 'rgba(0,0,0,0.25)', padding: '0 6px', borderRadius: '3px', margin: '0 4px' }}>python setup_auth.py</code>
          locally and restart the server.
        </div>
      ) : null}

      <div style={{ display: 'flex', gap: '8px', marginBottom: '12px', flexWrap: 'wrap' }}>
        <button
          className={`tab ${section === 'emails' ? 'active' : ''}`}
          onClick={() => setSection('emails')}
          style={{ padding: '0.35rem 0.8rem', fontSize: '0.85rem' }}
        >
          ✉ Emails drafted ({emailStats.total || 0})
        </button>
        <button
          className={`tab ${section === 'links' ? 'active' : ''}`}
          onClick={() => setSection('links')}
          style={{ padding: '0.35rem 0.8rem', fontSize: '0.85rem' }}
        >
          🔗 Apply via link ({linkStats.total || 0})
        </button>
        <button
          className={`tab ${section === 'pending' ? 'active' : ''}`}
          onClick={() => setSection('pending')}
          style={{ padding: '0.35rem 0.8rem', fontSize: '0.85rem' }}
        >
          ⏳ Pending ({connStats.pending || 0})
        </button>
        <button
          className={`tab ${section === 'ripening' ? 'active' : ''}`}
          onClick={() => setSection('ripening')}
          style={{ padding: '0.35rem 0.8rem', fontSize: '0.85rem' }}
        >
          ✍ Ready to DM ({connStats.accepted || 0})
        </button>
        <button
          className={`tab ${section === 'dms' ? 'active' : ''}`}
          onClick={() => setSection('dms')}
          style={{ padding: '0.35rem 0.8rem', fontSize: '0.85rem' }}
        >
          💬 DMs sent ({connStats.dm_sent || 0})
        </button>
        <button
          className={`tab ${section === 'failed' ? 'active' : ''}`}
          onClick={() => setSection('failed')}
          style={{ padding: '0.35rem 0.8rem', fontSize: '0.85rem' }}
        >
          ⚠ Failed ({connStats.dm_failed || 0})
        </button>
      </div>

      {loading ? <p style={{ color: 'var(--text-muted)' }}>Loading…</p> : null}

      {!loading && section === 'emails' ? (
        <OutreachEmailsList
          items={emails.items}
          onSetStatus={setEmailStatus}
          onRemove={removeEmail}
          onClear={clearEmails}
        />
      ) : null}

      {!loading && section === 'links' ? (
        <OutreachLinksList
          items={links.items}
          onSetStatus={setLinkStatus}
          onRemove={removeLink}
          onClear={clearLinks}
        />
      ) : null}

      {!loading && section === 'pending' ? (
        <OutreachConnectionsList items={connections.items} filter="pending" onSetStatus={setConnStatus} />
      ) : null}

      {!loading && section === 'ripening' ? (
        <OutreachConnectionsList items={connections.items} filter="accepted" onSetStatus={setConnStatus} />
      ) : null}

      {!loading && section === 'dms' ? (
        <OutreachConnectionsList items={connections.items} filter="dm_sent" onSetStatus={setConnStatus} />
      ) : null}

      {!loading && section === 'failed' ? (
        <OutreachConnectionsList items={connections.items} filter="dm_failed" onSetStatus={setConnStatus} />
      ) : null}
    </div>
  );
}


// Renders the full scraped post body — newlines preserved, scrollable so a
// long post doesn't blow up the list row. Used across the Outreach tab lists.
function PostBody({ text }) {
  if (!text) return null;
  return (
    <div style={{
      marginTop: '6px', fontSize: '0.78rem', color: 'var(--text-muted)',
      fontStyle: 'italic', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
      maxHeight: '260px', overflowY: 'auto', padding: '6px 8px',
      borderLeft: '2px solid var(--border)', background: 'rgba(255,255,255,0.02)',
      borderRadius: '4px',
    }}>
      "{text}"
    </div>
  );
}


function OutreachLinksList({ items, onSetStatus, onRemove, onClear }) {
  const statusColor = (s) => ({
    new: '#3b82f6', opened: '#a78bfa', applied: '#10b981', dismissed: 'var(--text-muted)',
  }[s] || 'var(--text-muted)');

  if (!items.length) {
    return (
      <p style={{ color: 'var(--text-muted)' }}>
        No apply-via-link posts yet. When the bot finds a hiring post that says
        "apply at &lt;url&gt;" or attaches an external ATS link, it lands here for you to open manually.
      </p>
    );
  }
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '8px' }}>
        <button className="btn secondary" onClick={onClear} style={{ margin: 0, padding: '0.35rem 0.7rem', fontSize: '0.78rem' }}>Clear all</button>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {items.map((it) => {
          const id = it.apply_url || it.post_url;
          const hostname = (() => { try { return new URL(it.apply_url).hostname.replace(/^www\./, ''); } catch { return it.apply_url; } })();
          return (
            <div key={id} style={{
              border: '1px solid var(--border)', borderRadius: '6px',
              padding: '10px 12px', background: 'var(--surface)',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'flex-start' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                    <span style={{ color: statusColor(it.status), fontWeight: 600, fontSize: '0.72rem', textTransform: 'uppercase' }}>{it.status}</span>
                    <strong>{it.post_author || 'Unknown author'}</strong>
                    {it.match_score != null ? (
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>· score {it.match_score}/100</span>
                    ) : null}
                  </div>
                  <div style={{ marginTop: '4px', fontSize: '0.92rem' }}>
                    <a href={it.apply_url} target="_blank" rel="noreferrer" style={{ color: '#60a5fa', fontWeight: 600 }}>
                      ↗ Apply on {hostname}
                    </a>
                  </div>
                  <div style={{ marginTop: '2px', fontSize: '0.78rem', color: 'var(--text-muted)', wordBreak: 'break-all' }}>
                    {it.apply_url}
                  </div>
                  <PostBody text={it.post_excerpt} />
                  <div style={{ marginTop: '4px', fontSize: '0.78rem', display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                    {it.post_url ? (
                      <a href={it.post_url} target="_blank" rel="noreferrer" style={{ color: '#60a5fa' }}>↗ original post</a>
                    ) : null}
                  </div>
                  <div style={{ marginTop: '2px', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                    captured {it.captured_at?.slice(0, 19).replace('T', ' ')}
                  </div>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', alignItems: 'stretch' }}>
                  {it.status !== 'opened' && (
                    <button className="btn secondary" onClick={() => onSetStatus(it, 'opened')} style={{ margin: 0, padding: '0.3rem 0.6rem', fontSize: '0.75rem' }}>👁 opened</button>
                  )}
                  {it.status !== 'applied' && (
                    <button className="btn secondary" onClick={() => onSetStatus(it, 'applied')} style={{ margin: 0, padding: '0.3rem 0.6rem', fontSize: '0.75rem' }}>✓ applied</button>
                  )}
                  {it.status !== 'dismissed' && (
                    <button className="btn secondary" onClick={() => onSetStatus(it, 'dismissed')} style={{ margin: 0, padding: '0.3rem 0.6rem', fontSize: '0.75rem' }}>dismiss</button>
                  )}
                  <button className="btn secondary" onClick={() => onRemove(it)} style={{ margin: 0, padding: '0.3rem 0.6rem', fontSize: '0.75rem' }}>🗑</button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}


function OutreachEmailsList({ items, onSetStatus, onRemove, onClear }) {
  const statusColor = (s) => ({
    drafted: '#3b82f6', sent: '#10b981', replied: '#a78bfa', ignored: 'var(--text-muted)',
    gmail_unauth: '#ef4444', gmail_failed: '#ef4444',
  }[s] || 'var(--text-muted)');
  const statusLabel = (s) => ({
    gmail_unauth: 'GMAIL AUTH NEEDED',
    gmail_failed: 'GMAIL ERROR',
  }[s] || s?.toUpperCase());

  if (!items.length) {
    return <p style={{ color: 'var(--text-muted)' }}>No email drafts yet. The bot will record one here every time it creates a Gmail draft from a post.</p>;
  }
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '8px' }}>
        <button className="btn secondary" onClick={onClear} style={{ margin: 0, padding: '0.35rem 0.7rem', fontSize: '0.78rem' }}>Clear all</button>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {items.map((it) => {
          const id = it.to_email || it.post_url;
          return (
            <div key={id} style={{
              border: '1px solid var(--border)', borderRadius: '6px',
              padding: '10px 12px', background: 'var(--surface)',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'flex-start' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                    <span style={{ color: statusColor(it.status), fontWeight: 600, fontSize: '0.72rem' }}>{statusLabel(it.status)}</span>
                    <strong>{it.to_email}</strong>
                    {it.match_score != null ? (
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>· score {it.match_score}/100</span>
                    ) : null}
                  </div>
                  {it.error ? (
                    <div style={{ marginTop: '2px', fontSize: '0.72rem', color: '#ef4444' }}>
                      {it.error}
                    </div>
                  ) : null}
                  <div style={{ marginTop: '4px', fontSize: '0.82rem' }}>
                    <span style={{ color: 'var(--text-muted)' }}>from post by</span>{' '}
                    <strong>{it.post_author || 'unknown'}</strong>
                  </div>
                  {it.subject ? (
                    <div style={{ marginTop: '4px', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                      Subject: {it.subject}
                    </div>
                  ) : null}
                  <PostBody text={it.post_excerpt} />
                  <details style={{ marginTop: '6px' }}>
                    <summary style={{ cursor: 'pointer', color: 'var(--text-muted)', fontSize: '0.78rem' }}>Show drafted body</summary>
                    <pre style={{
                      background: '#0b0b0e', color: '#e2e8f0', padding: '10px',
                      borderRadius: '4px', overflowX: 'auto', fontSize: '0.78rem',
                      whiteSpace: 'pre-wrap', marginTop: '6px', maxHeight: '300px',
                      overflowY: 'auto',
                    }}>{it.body}</pre>
                  </details>
                  <div style={{ marginTop: '4px', fontSize: '0.78rem', display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                    {it.post_url ? (
                      <a href={it.post_url} target="_blank" rel="noreferrer" style={{ color: '#60a5fa' }}>↗ original post</a>
                    ) : null}
                    <a href="https://mail.google.com/mail/u/0/#drafts" target="_blank" rel="noreferrer" style={{ color: '#60a5fa' }}>↗ open Gmail drafts</a>
                  </div>
                  <div style={{ marginTop: '2px', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                    created {it.created_at?.slice(0, 19).replace('T', ' ')}
                  </div>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', alignItems: 'stretch' }}>
                  {it.status !== 'sent' && (
                    <button className="btn secondary" onClick={() => onSetStatus(it, 'sent')} style={{ margin: 0, padding: '0.3rem 0.6rem', fontSize: '0.75rem' }}>✓ sent</button>
                  )}
                  {it.status !== 'replied' && (
                    <button className="btn secondary" onClick={() => onSetStatus(it, 'replied')} style={{ margin: 0, padding: '0.3rem 0.6rem', fontSize: '0.75rem' }}>↩ replied</button>
                  )}
                  {it.status !== 'ignored' && (
                    <button className="btn secondary" onClick={() => onSetStatus(it, 'ignored')} style={{ margin: 0, padding: '0.3rem 0.6rem', fontSize: '0.75rem' }}>ignore</button>
                  )}
                  <button className="btn secondary" onClick={() => onRemove(it)} style={{ margin: 0, padding: '0.3rem 0.6rem', fontSize: '0.75rem' }}>🗑</button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}


function OutreachConnectionsList({ items, filter, onSetStatus }) {
  const filtered = items.filter(it => it.status === filter);
  const statusColor = (s) => ({
    pending: '#f59e0b', accepted: '#10b981', dm_sent: '#10b981',
    dm_failed: '#ef4444', declined: 'var(--text-muted)',
  }[s] || 'var(--text-muted)');

  const emptyMessage = {
    pending: 'No pending connection requests. The bot queues one here every time it sends a connect-without-note from a post.',
    accepted: 'No DM drafts ready. A 1st-degree contact lands here right away; a 2nd/3rd-degree contact lands here once they accept the invite. Review the draft and send it yourself on LinkedIn.',
    dm_sent: 'No DMs marked sent yet. After you send a DM on LinkedIn, hit "✓ Mark DM sent" so it moves here.',
    dm_failed: 'No failed DMs.',
  };

  const copyDm = async (text) => {
    try { await navigator.clipboard.writeText(text || ''); } catch { /* clipboard blocked */ }
  };

  if (!filtered.length) {
    return <p style={{ color: 'var(--text-muted)' }}>{emptyMessage[filter] || 'No items.'}</p>;
  }

  // "accepted" = the DM draft is ready for the user to send manually.
  const isReady = filter === 'accepted';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      {filtered.map((it) => (
        <div key={it.profile_url} style={{
          border: '1px solid var(--border)', borderRadius: '6px',
          padding: '10px 12px', background: 'var(--surface)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            <span style={{ color: statusColor(it.status), fontWeight: 600, fontSize: '0.72rem', textTransform: 'uppercase' }}>
              {isReady ? 'ready to dm' : it.status}
            </span>
            <strong>{it.name || 'Unknown'}</strong>
            {it.dm_sent ? <span style={{ fontSize: '0.72rem', color: '#10b981' }}>✓ marked sent</span> : null}
          </div>
          <PostBody text={it.post_content} />
          {it.queued_dm ? (
            isReady ? (
              <div style={{ marginTop: '6px' }}>
                <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Draft DM — review, then send it yourself on LinkedIn:
                </div>
                <pre style={{
                  background: '#0b0b0e', color: '#e2e8f0', padding: '10px',
                  borderRadius: '4px', overflowX: 'auto', fontSize: '0.8rem',
                  whiteSpace: 'pre-wrap', margin: 0,
                }}>{it.queued_dm}</pre>
              </div>
            ) : (
              <details style={{ marginTop: '6px' }}>
                <summary style={{ cursor: 'pointer', color: 'var(--text-muted)', fontSize: '0.78rem' }}>
                  {it.status === 'dm_sent' ? 'Show DM' : 'Show DM draft'}
                </summary>
                <pre style={{
                  background: '#0b0b0e', color: '#e2e8f0', padding: '10px',
                  borderRadius: '4px', overflowX: 'auto', fontSize: '0.78rem',
                  whiteSpace: 'pre-wrap', marginTop: '6px',
                }}>{it.queued_dm}</pre>
              </details>
            )
          ) : null}
          <div style={{ marginTop: '8px', fontSize: '0.78rem', display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
            {it.profile_url ? (
              <a href={it.profile_url} target="_blank" rel="noreferrer" style={{ color: '#60a5fa' }}>↗ open profile</a>
            ) : null}
            {isReady ? (
              <>
                <button
                  className="btn secondary"
                  onClick={() => copyDm(it.queued_dm)}
                  style={{ margin: 0, padding: '0.3rem 0.6rem', fontSize: '0.75rem' }}
                >📋 copy DM</button>
                <button
                  className="btn"
                  onClick={() => onSetStatus?.(it, 'dm_sent')}
                  style={{ margin: 0, padding: '0.3rem 0.6rem', fontSize: '0.75rem' }}
                >✓ Mark DM sent</button>
              </>
            ) : null}
            {filter === 'dm_sent' ? (
              <button
                className="btn secondary"
                onClick={() => onSetStatus?.(it, 'accepted')}
                style={{ margin: 0, padding: '0.3rem 0.6rem', fontSize: '0.75rem' }}
              >↩ move back to Ready</button>
            ) : null}
          </div>
          <div style={{ marginTop: '4px', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
            queued {it.sent_at?.slice(0, 19).replace('T', ' ')}
            {it.last_checked_at ? ` · last checked ${it.last_checked_at.slice(0, 19).replace('T', ' ')}` : ''}
          </div>
        </div>
      ))}
    </div>
  );
}


function ExternalLeadsManager({ showToast }) {
  const [items, setItems] = useState([]);
  const [stats, setStats] = useState({ total: 0, new: 0, viewed: 0, applied: 0, dismissed: 0 });
  const [filter, setFilter] = useState('all');
  const [loading, setLoading] = useState(true);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/external-leads');
      const data = await res.json();
      setItems(data.items || []);
      setStats(data.stats || {});
    } catch (err) {
      showToast?.({ message: `Failed to load leads: ${err.message}`, type: 'error' });
    }
    setLoading(false);
  };

  useEffect(() => { fetchAll(); }, []);

  const setStatus = async (lead, status) => {
    const id = lead.job_identifier || lead.url;
    try {
      await fetch('/api/external-leads/status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ identifier: id, status }),
      });
      await fetchAll();
    } catch (err) {
      showToast?.({ message: `Status update failed: ${err.message}`, type: 'error' });
    }
  };

  const removeLead = async (lead) => {
    const id = lead.job_identifier || lead.url;
    if (!window.confirm(`Remove "${lead.title || lead.url}" from leads?`)) return;
    try {
      await fetch('/api/external-leads/remove', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ identifier: id }),
      });
      await fetchAll();
    } catch (err) {
      showToast?.({ message: `Remove failed: ${err.message}`, type: 'error' });
    }
  };

  const clearAll = async () => {
    if (!items.length) return;
    if (!window.confirm(`Delete all ${items.length} lead(s)? This cannot be undone.`)) return;
    try {
      await fetch('/api/external-leads/clear', { method: 'POST' });
      await fetchAll();
      showToast?.({ message: 'Leads cleared.', type: 'success' });
    } catch (err) {
      showToast?.({ message: `Clear failed: ${err.message}`, type: 'error' });
    }
  };

  const filtered = filter === 'all' ? items : items.filter(it => it.status === filter);
  const statusColor = (s) => ({
    new: '#3b82f6', viewed: '#a78bfa', applied: '#10b981', dismissed: 'var(--text-muted)'
  }[s] || 'var(--text-muted)');

  return (
    <div className="card" style={{ padding: '1rem', marginTop: '1rem' }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.8rem', flexWrap: 'wrap', gap: '8px' }}>
        <div>
          <h3 style={{ margin: 0 }}>External-ATS Leads ({stats.total || 0})</h3>
          <p style={{ margin: '4px 0 0', color: 'var(--text-muted)', fontSize: '0.82rem' }}>
            Jobs the bot couldn't Easy-Apply (external redirect or modal that never opened). Apply manually.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
          <select value={filter} onChange={(e) => setFilter(e.target.value)} style={{
            background: 'var(--background)', color: 'var(--text-main)',
            border: '1px solid var(--border)', padding: '0.35rem 0.6rem',
            borderRadius: '6px', fontSize: '0.82rem',
          }}>
            <option value="all">all ({stats.total || 0})</option>
            <option value="new">new ({stats.new || 0})</option>
            <option value="viewed">viewed ({stats.viewed || 0})</option>
            <option value="applied">applied ({stats.applied || 0})</option>
            <option value="dismissed">dismissed ({stats.dismissed || 0})</option>
          </select>
          <button className="btn secondary" onClick={fetchAll} style={{ margin: 0, padding: '0.4rem 0.8rem', fontSize: '0.85rem' }}>Refresh</button>
          <button className="btn secondary" onClick={clearAll} disabled={!items.length} style={{ margin: 0, padding: '0.4rem 0.8rem', fontSize: '0.85rem' }}>Clear all</button>
        </div>
      </header>

      {loading ? <p style={{ color: 'var(--text-muted)' }}>Loading…</p> : null}
      {!loading && filtered.length === 0 ? (
        <p style={{ color: 'var(--text-muted)' }}>No leads in this view.</p>
      ) : null}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {filtered.map((lead) => {
          const linkedinUrl = lead.url || '';
          const externalUrl = lead.destination_url || '';
          const id = lead.job_identifier || lead.url;
          return (
            <div key={id} style={{
              border: '1px solid var(--border)', borderRadius: '6px',
              padding: '10px 12px', background: 'var(--surface)',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                    <span style={{ color: statusColor(lead.status), fontWeight: 600, fontSize: '0.72rem', textTransform: 'uppercase' }}>
                      {lead.status}
                    </span>
                    <strong>{lead.title || 'Untitled'}</strong>
                    {lead.company ? <span style={{ color: 'var(--text-muted)' }}>· {lead.company}</span> : null}
                  </div>
                  <div style={{ marginTop: '4px', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                    {lead.reason || ''}
                  </div>
                  <div style={{ marginTop: '4px', fontSize: '0.82rem', display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                    {linkedinUrl ? (
                      <a href={linkedinUrl} target="_blank" rel="noreferrer" style={{ color: '#60a5fa' }}>↗ LinkedIn</a>
                    ) : null}
                    {externalUrl ? (
                      <a href={externalUrl} target="_blank" rel="noreferrer" style={{ color: '#60a5fa' }}>
                        ↗ {externalUrl.replace(/^https?:\/\//, '').slice(0, 60)}
                      </a>
                    ) : null}
                  </div>
                  <div style={{ marginTop: '2px', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                    captured {lead.captured_at?.slice(0, 19).replace('T', ' ')}
                  </div>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', alignItems: 'stretch' }}>
                  {lead.status !== 'applied' && (
                    <button className="btn secondary" onClick={() => setStatus(lead, 'applied')} style={{ margin: 0, padding: '0.3rem 0.6rem', fontSize: '0.75rem' }}>✓ applied</button>
                  )}
                  {lead.status !== 'viewed' && lead.status !== 'applied' && (
                    <button className="btn secondary" onClick={() => setStatus(lead, 'viewed')} style={{ margin: 0, padding: '0.3rem 0.6rem', fontSize: '0.75rem' }}>viewed</button>
                  )}
                  {lead.status !== 'dismissed' && (
                    <button className="btn secondary" onClick={() => setStatus(lead, 'dismissed')} style={{ margin: 0, padding: '0.3rem 0.6rem', fontSize: '0.75rem' }}>dismiss</button>
                  )}
                  <button className="btn secondary" onClick={() => removeLead(lead)} style={{ margin: 0, padding: '0.3rem 0.6rem', fontSize: '0.75rem' }}>🗑</button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
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
  const [backendOnline, setBackendOnline] = useState(true);
  const [logs, setLogs] = useState([{ message: 'System initialized. Awaiting commands.', type: 'system', time: new Date().toLocaleTimeString() }]);

  const [stats, setStats] = useState({ jobsSearched: 0, profilesFound: 0, postsFound: 0, applicationsSent: 0, draftsCreated: 0 });
  const [activityDetails, setActivityDetails] = useState({ jobs: [], profiles: [], posts: [] });
  const [activeDetails, setActiveDetails] = useState(null);
  const [toast, setToast] = useState(null);

  const eventSourceRef = useRef(null);
  const logsEndRef = useRef(null);
  // Guard so the mount-time log replay + SSE reattach only runs once. loadAll()
  // is also called on a 4s retry while the backend is offline; without this guard
  // every successful retry would re-replay the buffer and double-log everything.
  const initialRecoveryDoneRef = useRef(false);

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

  // Single SSE-message handler used by both the live stream (startAgent) and
  // mount-time replay (loadAll). `isReplay=true` skips client-side stats
  // increments because /api/db already reflects the final post-run counts —
  // re-incrementing on replay would inflate the dashboard tiles.
  const handleLogPayload = (data, { isReplay = false } = {}) => {
    if (data.action === 'PAUSED') setIsPaused(true);
    else if (data.action === 'RESUMED') setIsPaused(false);
    else if (data.action === 'ASK_HUMAN' && data.question) setPendingQuestion(data.question);
    else if (data.action === 'ANSWER_HUMAN') setPendingQuestion(prev => (prev && prev.id === data.question_id ? null : prev));

    addLog(data.message, data.type || 'info', {
      action: data.action,
      detail: data.detail,
      post_batch: data.post_batch,
    });

    if (data.detail) {
      setActivityDetails(prev => {
        const bucket = data.detail.kind === 'Job' ? 'jobs'
          : data.detail.kind === 'Post' ? 'posts' : 'profiles';
        return { ...prev, [bucket]: upsertDetail(prev[bucket], data.detail, data.action) };
      });
    }

    if (!isReplay) {
      if (data.action === 'SEARCHED_JOB' && data.detail) {
        setStats(s => ({ ...s, jobsSearched: s.jobsSearched + 1 }));
      } else if (data.action === 'SEARCHED_POST' && data.detail) {
        setStats(s => ({ ...s, postsFound: (s.postsFound ?? 0) + 1 }));
      } else if (data.action === 'SEARCHED_PERSON' && data.detail) {
        setStats(s => ({ ...s, profilesFound: s.profilesFound + 1 }));
      } else if (data.action === 'APPLIED') {
        setStats(s => ({ ...s, applicationsSent: s.applicationsSent + 1 }));
      } else if (data.action === 'DRAFTED_EMAIL' || data.action === 'DRAFTED_DM') {
        setStats(s => ({ ...s, draftsCreated: s.draftsCreated + 1 }));
      }
    }

    if (data.action === 'DONE') {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      setIsRunning(false);
    }
  };

  // Opens the SSE log stream. Called both after /api/start succeeds and on
  // mount when /api/run-status says a run is in progress (so a page refresh
  // mid-run reattaches instead of leaving the UI stuck in idle).
  const attachLogStream = () => {
    if (eventSourceRef.current) eventSourceRef.current.close();
    const source = new EventSource('/api/logs');
    eventSourceRef.current = source;
    source.onmessage = (event) => {
      try {
        handleLogPayload(JSON.parse(event.data));
      } catch (err) {
        addLog(`Bad SSE payload: ${err.message}`, 'error');
      }
    };
    source.onerror = () => {
      source.close();
      eventSourceRef.current = null;
      addLog('Lost connection to stream.', 'error');
      setIsRunning(false);
    };
  };

  useEffect(() => {
    // Subscribe to backend-online signal coming from apiFetch.
    const unsub = backendStatus.subscribe(setBackendOnline);

    const loadAll = async () => {
      try {
        const r = await apiFetch('/api/db');
        const data = await r.json();
        if (data.stats) setStats(data.stats);
        if (data.history) setActivityDetails({ jobs: data.history.jobs || [], profiles: data.history.profiles || [], posts: data.history.posts || [] });
      } catch { /* backendStatus flipped */ }
      try {
        const r = await apiFetch('/api/models');
        const data = await r.json();
        if (data.models && data.models.length > 0) setAvailableModels(data.models);
        if (data.warning) addLog(data.warning, 'warning');
      } catch { /* */ }
      try {
        const r = await apiFetch('/api/login-status');
        const data = await r.json();
        setLoginStatus(data.logged_in);
      } catch {
        setLoginStatus(false);
      }

      // ── First-load recovery: replay live-log buffer and reattach SSE if a run
      // is in progress. This is what makes a page refresh during a run NOT
      // appear as "everything reset". Only run once per mount; the 4s retry
      // loop above still works for /api/db reloads but skips recovery.
      if (initialRecoveryDoneRef.current) return;
      try {
        const runRes = await apiFetch('/api/run-status');
        const runData = await runRes.json();
        const logsRes = await apiFetch('/api/recent-logs');
        const logsData = await logsRes.json();
        const replayLogs = Array.isArray(logsData.logs) ? logsData.logs : [];

        initialRecoveryDoneRef.current = true;

        if (replayLogs.length > 0) {
          // Drop the "System initialized" placeholder and rebuild the log feed
          // from the server-side ring buffer.
          setLogs([]);
          for (const payload of replayLogs) {
            handleLogPayload(payload, { isReplay: true });
          }
        }
        if (runData.is_running) {
          setIsRunning(true);
          setIsPaused(!!runData.is_paused);
          attachLogStream();
        }
      } catch { /* recovery is best-effort */ }
    };

    loadAll();
    // Retry the initial load every 4s while the backend is offline.
    const interval = setInterval(() => {
      if (!backendStatus.online) loadAll();
    }, 4000);

    return () => { clearInterval(interval); unsub(); };
  }, []);

  const handleClearDb = async () => {
    if (!window.confirm('Clear all stats and processed-job history? This cannot be undone.')) return;
    try {
      const res = await fetch('/api/db/reset', { method: 'POST' });
      const data = await res.json();
      if (data.status === 'success') {
        setStats({ jobsSearched: 0, profilesFound: 0, postsFound: 0, applicationsSent: 0, draftsCreated: 0 });
        setActivityDetails({ jobs: [], profiles: [], posts: [] });
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

      attachLogStream();

    } catch (err) {
      addLog(`Failed to start agent: ${err.message}`, 'error');
      stopAgent();
    }
  };

  return (
    <>
      {!backendOnline && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, zIndex: 9500,
          background: '#7f1d1d', color: '#fff', padding: '8px 16px',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          boxShadow: '0 2px 8px rgba(0,0,0,0.3)', fontSize: '0.88rem',
        }}>
          <span>⚠ Backend offline at http://127.0.0.1:8000 — start it with <code style={{ background: 'rgba(0,0,0,0.3)', padding: '0 6px', borderRadius: '3px' }}>python server.py</code>. Retrying every 4s…</span>
        </div>
      )}
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
