import { useState, useEffect, useMemo, type ReactNode } from 'react';

// Environment variables (set in .env)
const OWNER_USER_ID = process.env.NEXT_PUBLIC_OWNER_USER_ID;
const HARNESS_ANNOTATION_ID = process.env.NEXT_PUBLIC_HARNESS_ANNOTATION_ID;
const WORKSPACE_PATH = process.env.NEXT_PUBLIC_WORKSPACE_PATH;

interface Event {
  step: string;
  status: string;
  timestamp: string;
  detail: string;
}

interface Run {
  run_id: string;
  events: Event[];
}

export default function HarnessDashboard() {
  const [currentUser, setCurrentUser] = useState<any>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [currentRun, setCurrentRun] = useState<Run | null>(null);
  const [outstandingIssues, setOutstandingIssues] = useState<string>('');

  const isOwner = currentUser?.id === OWNER_USER_ID;

  // Flow chart lookups for the currently selected run
  const stepMap = useMemo(
    () => new Map((currentRun?.events || []).map((e) => [e.step, e])),
    [currentRun]
  );
  const hasStep = (step: string) => stepMap.has(step);
  const getStep = (step: string) => stepMap.get(step);

  // Which branches of the constant flow chart this run actually took.
  const projectComplete = hasStep('FIND_MILESTONE') && !hasStep('GENERATE');
  const reviewFailed =
    hasStep('REVIEW') &&
    !hasStep('MARK_COMPLETE') &&
    (hasStep('RUN_COMPLETE') || hasStep('RUN_INCOMPLETE'));
  // Retries remaining => milestone left incomplete but the run still completes.
  const retryScheduled = reviewFailed && hasStep('RUN_COMPLETE');

  async function fetchCurrentUser() {
    // Resolve the current user through a backend route (never the Fulcra API
    // directly) so the browser holds no token and there is no CORS. The route
    // returns the authenticated user, including the `id` we match against
    // OWNER_USER_ID below.
    try {
      const res = await fetch('/api/me');
      if (!res.ok) return;
      const user = await res.json();
      setCurrentUser(user);
    } catch (e) {
      console.error('Failed to fetch current user:', e);
    }
  }

  async function fetchRuns() {
    try {
      // Fetch through a backend API route (not the Fulcra API directly) to
      // avoid CORS. This mirrors the Svelte harness-api-server.js contract:
      // the route proxies GET data/v1alpha1/event/{annotation_id}.
      // Query a rolling 30-day window ending today.
      const end = new Date();
      const start = new Date(end.getTime() - 30 * 24 * 60 * 60 * 1000);
      const startDate = start.toISOString().slice(0, 10);
      const endDate = end.toISOString().slice(0, 10);
      const res = await fetch(
        `/api/harness/runs?annotation_id=${encodeURIComponent(
          HARNESS_ANNOTATION_ID!
        )}&start_date=${startDate}&end_date=${endDate}`
      );
      const data = await res.json();

      // Extract records from the response
      const records = data.records || data || [];

      // Group by run_id. Harness data is stored as a JSON string in the
      // annotation's `note` field; fall back to flat fields for other shapes.
      const runMap = new Map<string, Run>();
      records.forEach((record: any) => {
        let harnessData: any;
        try {
          harnessData = record.note ? JSON.parse(record.note) : record.data || record;
        } catch (e) {
          console.error('Failed to parse note as JSON:', record.note);
          return;
        }

        const runId = harnessData.run_id;
        const step = harnessData.step;
        const status = harnessData.status;
        const detail = harnessData.detail || '';
        const timestamp = record.recorded_at || record.moment || record.timestamp;

        if (!runId || !step) return; // Skip records without required fields

        if (!runMap.has(runId)) {
          runMap.set(runId, { run_id: runId, events: [] });
        }
        runMap.get(runId)!.events.push({ step, status, timestamp, detail });
      });

      const runsArray = Array.from(runMap.values());
      // Sort each run's events chronologically so the last event is the newest
      // one — getRunStatus and the per-step lookup both rely on latest-wins,
      // and long steps emit several records that may arrive out of order.
      runsArray.forEach((r) =>
        r.events.sort((a, b) => (a.timestamp || '').localeCompare(b.timestamp || ''))
      );
      runsArray.sort((a, b) => {
        const aTime = a.events[0]?.timestamp || '';
        const bTime = b.events[0]?.timestamp || '';
        return bTime.localeCompare(aTime);
      });

      setRuns(runsArray);
      // Preserve the user's selection across polls; only default to the
      // latest run when nothing is selected yet or the selection disappeared.
      setCurrentRun(
        (prev) => runsArray.find((r) => r.run_id === prev?.run_id) || runsArray[0] || null
      );
    } catch (e) {
      console.error('Failed to fetch runs:', e);
      setRuns([]);
      setCurrentRun(null);
    }
  }

  async function fetchOutstandingIssues() {
    try {
      const res = await fetch(
        `/api/harness/issues?workspace_path=${encodeURIComponent(WORKSPACE_PATH!)}`
      );
      const issues = await res.text();
      setOutstandingIssues(issues);
    } catch (e) {
      setOutstandingIssues('');
    }
  }

  useEffect(() => {
    fetchCurrentUser();
  }, []);

  useEffect(() => {
    if (isOwner) {
      fetchRuns();
      fetchOutstandingIssues();

      // Refresh every 5 seconds
      const interval = setInterval(() => {
        fetchRuns();
        fetchOutstandingIssues();
      }, 5000);

      return () => clearInterval(interval);
    }
  }, [isOwner]);

  function getRunStatus(run: Run): string {
    const lastEvent = run.events[run.events.length - 1];
    if (lastEvent.step === 'RUN_COMPLETE') return 'completed';
    if (lastEvent.step === 'RUN_INCOMPLETE') return 'incomplete';
    if (lastEvent.step === 'ESCALATE') return 'escalated';
    return 'in-progress';
  }

  function formatTimestamp(ts: string): string {
    return new Date(ts).toLocaleString();
  }

  // Renders one process box, highlighted when this run reached that step.
  function stepBox(key: string, name: string, extra = ''): ReactNode {
    const step = getStep(key);
    return (
      <div className={`flow-step-box ${extra} ${hasStep(key) ? 'active' : ''}`}>
        <div className="step-header">
          <span className="step-name">{name}</span>
          {step && <span className={`status-badge status-${step.status}`}>{step.status}</span>}
        </div>
        {step && step.detail && <div className="step-detail">{step.detail}</div>}
      </div>
    );
  }

  if (!isOwner) return null;

  return (
    <div className="harness-dashboard">
      <h2>Harness Dashboard</h2>

      {/* Run History - compact, scrollable */}
      <div className="run-history">
        <h3>Recent Runs</h3>
        <div className="run-list">
          {runs.slice(0, 3).map((run) => (
            <button
              key={run.run_id}
              className={`run-item ${run === currentRun ? 'active' : ''}`}
              onClick={() => setCurrentRun(run)}
            >
              <div className="run-header">
                <span className="run-id">{run.run_id}</span>
                <span className={`status-badge status-${getRunStatus(run)}`}>
                  {getRunStatus(run)}
                </span>
              </div>
              <div className="run-time">{formatTimestamp(run.events[0]?.timestamp)}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Current Run with Flow Diagram */}
      {currentRun && (
        <div className="current-run-flow">
          <div className="current-run-header">
            <h3>Run: {currentRun.run_id}</h3>
            <span className={`run-status status-${getRunStatus(currentRun)}`}>
              {getRunStatus(currentRun)}
            </span>
          </div>

          <div className="flow-chart">
            <div className="flow-body">
              {/* Nurse pre-check: its own column, runs before the main loop */}
              <div className="nurse-band nurse-col">
                <div className="nurse-label">🩺 Nurse pre-check</div>
                <div className="flow-decision-box nurse">
                  <div className="decision-text">Previous run completed?</div>
                </div>
                <div className="flow-h-arrow labeled vert">No ↓</div>
                <div className="flow-decision-box nurse">
                  <div className="decision-text">Fix attempts remain?</div>
                </div>
                <div className={`branch-item ${hasStep('FIX_ATTEMPT') ? 'active' : ''}`}>
                  <span className="branch-tag">Yes ↓</span>
                  {stepBox('FIX_ATTEMPT', '🩺 Attempt Fix', 'small')}
                </div>
                <div className={`branch-item ${hasStep('ESCALATE') ? 'active' : ''}`}>
                  <span className="branch-tag">No ↓</span>
                  {stepBox('ESCALATE', '🩺 Escalate — Loop Ends', 'small')}
                </div>
              </div>

              <div className="flow-h-arrow labeled connector">
                Healthy
                <br />
                or fixed →
              </div>

              {/* Main harness loop */}
              <div className="main-flow">
                {/* Milestone selection */}
                <div className="flow-grid">
                  {stepBox('FIND_MILESTONE', '🎛️ Find Incomplete Milestone', 'small')}
                  <div className="flow-h-arrow">→</div>
                  <div className="flow-decision-box inline">
                    <div className="decision-text">🎛️ Any incomplete milestone?</div>
                  </div>
                  <div className="flow-h-arrow labeled">No →</div>
                  <div className={`branch-item ${projectComplete ? 'active' : ''}`}>
                    <div className="flow-terminal complete small">Project Complete</div>
                  </div>
                </div>
                <div className="flow-arrow">↓</div>

                {/* Generate → review → decision */}
                <div className="flow-grid">
                  {stepBox('GENERATE', '✍️ Generate Code', 'small')}
                  <div className="flow-h-arrow">→</div>
                  {stepBox('REVIEW', '⚖️ Review Code', 'small')}
                  <div className="flow-h-arrow">→</div>
                  <div className="flow-decision-box inline">
                    <div className="decision-text">🎛️ Review passed?</div>
                  </div>
                </div>
                <div className="flow-arrow">↓</div>

                {/* Review outcomes: Yes comes first; No spans the other two columns */}
                <div className="flow-grid outcomes">
                  <div className={`outcome-yes ${hasStep('MARK_COMPLETE') ? 'active' : ''}`}>
                    <div className="path-label">Yes</div>
                    {stepBox('MARK_COMPLETE', '🎛️ Mark Milestone Complete', 'small')}
                    <div className="flow-arrow">↓</div>
                    <div className="flow-terminal complete small">Run Complete</div>
                  </div>
                  <div className={`outcome-no ${reviewFailed ? 'active' : ''}`}>
                    <div className="path-label">No</div>
                    <div className="flow-decision-box small">
                      <div className="decision-text">🎛️ Retries remain?</div>
                    </div>
                    <div className="flow-split tight">
                      <div className={`flow-path ${retryScheduled ? 'active' : ''}`}>
                        <div className="path-label">Yes</div>
                        <div className="flow-terminal retry small">
                          Leave Incomplete — Retry Next Run
                        </div>
                      </div>
                      <div className={`flow-path ${hasStep('RUN_INCOMPLETE') ? 'active' : ''}`}>
                        <div className="path-label">No</div>
                        <div className="flow-terminal incomplete small">End Run — Incomplete</div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Outstanding Issues */}
      {outstandingIssues && (
        <div className="outstanding-issues">
          <h3>Outstanding Issues</h3>
          <div className="issues-content" dangerouslySetInnerHTML={{ __html: outstandingIssues }} />
        </div>
      )}

      <style jsx>{`
        .harness-dashboard {
          padding: 2rem;
          max-width: 1200px;
          margin: 0 auto;
          color: var(--color-fulcra-black);
        }

        .harness-dashboard h2,
        .harness-dashboard h3 {
          color: var(--color-fulcra-black);
        }

        .run-history {
          margin-bottom: 2rem;
        }

        .run-list {
          display: flex;
          gap: 1rem;
          overflow-x: auto;
          padding-bottom: 0.5rem;
        }

        .run-item {
          flex: 0 0 300px;
          background: var(--color-fulcra-white);
          border: 2px solid var(--color-fulcra-black-25);
          border-radius: 8px;
          padding: 1rem;
          cursor: pointer;
          transition: all 0.2s;
          text-align: left;
        }

        .run-item:hover {
          border-color: var(--color-fulcra-teal);
        }

        .run-item.active {
          border-color: var(--color-fulcra-teal);
          background: var(--color-fulcra-teal-10);
        }

        .run-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 0.5rem;
        }

        .run-id {
          font-family: monospace;
          font-size: 0.875rem;
          font-weight: 600;
        }

        .run-time {
          color: var(--color-fulcra-gray);
          font-size: 0.75rem;
          margin-top: 0.25rem;
        }

        .current-run-flow {
          background: var(--color-fulcra-white);
          border: 1px solid var(--color-fulcra-black-25);
          border-radius: 8px;
          padding: 1.5rem;
          margin-bottom: 2rem;
        }

        .current-run-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 1rem;
          margin-bottom: 1.5rem;
        }

        .current-run-header h3 {
          margin: 0;
        }

        .run-status {
          display: inline-block;
          padding: 0.35rem 0.85rem;
          border-radius: 4px;
          font-weight: 600;
          font-size: 0.875rem;
          text-transform: capitalize;
          white-space: nowrap;
        }

        .status-completed {
          background: var(--color-fulcra-teal-10);
          color: var(--color-fulcra-green-100);
        }
        .status-in-progress {
          background: var(--color-fulcra-lavender-25);
          color: var(--color-fulcra-purple-100);
        }
        .status-incomplete {
          background: #ffcdd2;
          color: var(--color-fulcra-error);
        }
        .status-escalated {
          background: #ffe0b2;
          color: #e65100;
        }

        .flow-chart {
          /* Three equal process columns with fixed arrow gutters between them.
             Fixed track sizes mean every .flow-grid row is the same total width,
             so the columns line up vertically across rows. */
          --flow-col: 185px;
          --arrow-w: 2.25rem;
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 0;
          overflow-x: auto;
        }

        .flow-step-box {
          width: 100%;
          max-width: 600px;
          padding: 1.25rem;
          background: var(--color-fulcra-white);
          border: 2px solid var(--color-fulcra-black-25);
          border-radius: 8px;
          opacity: 0.3;
          transition: all 0.2s;
        }

        .flow-step-box.small {
          max-width: 400px;
          padding: 1rem;
        }

        .flow-step-box.active {
          opacity: 1;
          border-color: var(--color-fulcra-teal);
          background: var(--color-fulcra-teal-10);
        }

        .flow-decision-box {
          width: 100%;
          max-width: 600px;
          padding: 1rem 1.5rem;
          background: var(--color-fulcra-lavender-25);
          border: 2px solid var(--color-fulcra-purple);
          border-radius: 8px;
          text-align: center;
          margin: 0.5rem 0;
        }

        .flow-decision-box.small {
          max-width: 340px;
          padding: 0.6rem 1rem;
        }

        .flow-decision-box.nurse {
          background: #ffe0b2;
          border-color: #f57c00;
        }

        .decision-text {
          font-weight: 600;
          font-size: 1rem;
          color: var(--color-fulcra-purple-100);
        }

        .flow-decision-box.small .decision-text {
          font-size: 0.875rem;
        }

        .flow-decision-box.nurse .decision-text {
          color: #e65100;
        }

        .flow-terminal {
          padding: 0.6rem 1.25rem;
          border-radius: 999px;
          font-weight: 700;
          font-size: 0.875rem;
          text-align: center;
          border: 2px solid var(--color-fulcra-black-25);
          background: var(--color-fulcra-white);
          color: var(--color-fulcra-black);
        }

        .flow-terminal.small {
          font-size: 0.8rem;
          padding: 0.45rem 1rem;
        }

        .flow-terminal.complete {
          background: var(--color-fulcra-teal-10);
          border-color: var(--color-fulcra-teal);
          color: var(--color-fulcra-green-100);
        }

        .flow-terminal.retry {
          background: var(--color-fulcra-lavender-25);
          border-color: var(--color-fulcra-purple);
          color: var(--color-fulcra-purple-100);
        }

        .flow-terminal.incomplete {
          background: #ffcdd2;
          border-color: var(--color-fulcra-error);
          color: var(--color-fulcra-error);
        }

        .flow-grid {
          display: grid;
          grid-template-columns:
            var(--flow-col) var(--arrow-w) var(--flow-col) var(--arrow-w) var(--flow-col);
          align-items: center;
          justify-items: center;
          row-gap: 0.4rem;
          width: max-content;
          max-width: 100%;
          margin: 0.15rem auto;
        }

        /* Direct children of a grid row fill their column exactly */
        .flow-grid > .flow-step-box,
        .flow-grid > .flow-decision-box {
          width: var(--flow-col);
          max-width: none;
          box-sizing: border-box;
          margin: 0;
        }

        /* Nurse pre-check lives in its own column to the left of the main loop */
        .flow-body {
          display: flex;
          align-items: flex-start;
          justify-content: center;
          gap: 0.5rem;
        }

        .main-flow {
          display: flex;
          flex-direction: column;
          align-items: center;
        }

        .nurse-band {
          background: #fff8f0;
          border: 1px dashed #f57c00;
          border-radius: 10px;
          padding: 0.75rem;
        }

        .nurse-col {
          display: flex;
          flex-direction: column;
          align-items: stretch;
          gap: 0.35rem;
          width: calc(var(--flow-col) + 1.5rem);
          box-sizing: border-box;
        }

        .nurse-label {
          font-size: 0.8rem;
          font-weight: 700;
          color: #e65100;
          text-align: center;
          margin-bottom: 0.15rem;
        }

        .nurse-col .flow-decision-box {
          width: 100%;
          max-width: none;
          margin: 0;
          padding: 0.6rem 0.9rem;
          box-sizing: border-box;
        }

        .nurse-col .flow-step-box {
          width: 100%;
          max-width: none;
          box-sizing: border-box;
        }

        .flow-h-arrow.vert {
          text-align: center;
        }

        .flow-h-arrow.connector {
          align-self: flex-start;
          margin-top: 2.5rem;
          text-align: center;
          line-height: 1.2;
        }

        .flow-h-arrow {
          font-size: 1.25rem;
          color: var(--color-fulcra-gray);
          line-height: 1;
        }

        .flow-h-arrow.labeled {
          font-size: 0.8rem;
          font-weight: 600;
        }

        .flow-decision-box.inline {
          padding: 0.6rem 0.9rem;
        }

        .flow-decision-box.inline .decision-text {
          font-size: 0.85rem;
        }

        .branch-tag {
          font-size: 0.75rem;
          font-weight: 600;
          color: var(--color-fulcra-gray);
        }

        .branch-item {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 0.15rem;
          opacity: 0.3;
          transition: opacity 0.2s;
        }

        .branch-item.active {
          opacity: 1;
        }

        /* Review outcomes row: Yes sits in column 1, No spans the other two */
        .outcomes {
          align-items: start;
          row-gap: 0;
        }

        .outcome-no {
          grid-column: 3 / span 3;
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 0.4rem;
          width: 100%;
          opacity: 0.3;
          transition: opacity 0.2s;
        }

        .outcome-yes {
          grid-column: 1;
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 0.4rem;
          width: var(--flow-col);
          opacity: 0.3;
          transition: opacity 0.2s;
        }

        .outcome-yes .flow-step-box {
          width: 100%;
          max-width: none;
          box-sizing: border-box;
        }

        .outcome-no.active,
        .outcome-yes.active {
          opacity: 1;
        }

        .flow-split {
          display: flex;
          gap: 1rem;
          justify-content: center;
        }

        .flow-split.tight {
          gap: 1rem;
          margin: 0.25rem 0 0;
        }

        .flow-path {
          flex: 1;
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 0.5rem;
          opacity: 0.3;
          transition: opacity 0.2s;
        }

        .flow-path.active {
          opacity: 1;
        }

        .path-label {
          font-weight: 600;
          color: var(--color-fulcra-gray);
          font-size: 0.875rem;
        }

        .flow-arrow {
          font-size: 1.5rem;
          color: var(--color-fulcra-gray);
          line-height: 1;
          padding: 0.25rem 0;
        }

        .step-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 0.75rem;
        }

        .step-name {
          font-weight: 600;
          font-size: 1rem;
          color: var(--color-fulcra-black);
        }

        .status-badge {
          display: inline-block;
          padding: 0.25rem 0.5rem;
          border-radius: 3px;
          font-size: 0.75rem;
          font-weight: 500;
        }

        .status-started {
          background: var(--color-fulcra-lavender-50);
          color: var(--color-fulcra-purple-100);
        }
        .status-failed {
          background: #ffcdd2;
          color: var(--color-fulcra-error);
        }

        .step-detail {
          color: var(--color-fulcra-black);
          font-size: 0.875rem;
          margin-bottom: 0.5rem;
          line-height: 1.5;
        }

        .outstanding-issues {
          background: var(--color-fulcra-lavender-25);
          border: 1px solid var(--color-fulcra-purple);
          border-radius: 8px;
          padding: 1.5rem;
        }

        .issues-content {
          font-size: 0.875rem;
          color: var(--color-fulcra-purple-100);
        }
      `}</style>
    </div>
  );
}
