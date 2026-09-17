import { useState, useEffect } from 'react';

// Environment variables (set in .env)
const OWNER_USER_ID = process.env.NEXT_PUBLIC_OWNER_USER_ID;
const HARNESS_ANNOTATION_ID = process.env.NEXT_PUBLIC_HARNESS_ANNOTATION_ID;
const WORKSPACE_PATH = process.env.NEXT_PUBLIC_WORKSPACE_PATH;
const FULCRA_API_URL = process.env.NEXT_PUBLIC_FULCRA_API_URL;

interface Event {
  run_id: string;
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

  async function fetchCurrentUser() {
    const res = await fetch(`${FULCRA_API_URL}/me`);
    const user = await res.json();
    setCurrentUser(user);
  }

  async function fetchRuns() {
    const res = await fetch(`${FULCRA_API_URL}/annotations/${HARNESS_ANNOTATION_ID}/records`);
    const records = await res.json();

    // Group by run_id and build timeline
    const runMap = new Map<string, Run>();
    records.forEach((r: Event) => {
      if (!runMap.has(r.run_id)) {
        runMap.set(r.run_id, { run_id: r.run_id, events: [] });
      }
      runMap.get(r.run_id)!.events.push(r);
    });

    const runsArray = Array.from(runMap.values()).sort((a, b) => {
      const aTime = a.events[0]?.timestamp || '';
      const bTime = b.events[0]?.timestamp || '';
      return bTime.localeCompare(aTime);
    });

    setRuns(runsArray);
    setCurrentRun(runsArray[0] || null);
  }

  async function fetchOutstandingIssues() {
    try {
      const res = await fetch(`${FULCRA_API_URL}/files/${WORKSPACE_PATH}/outstanding-issues.md`);
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

  if (!isOwner) return null;

  return (
    <div className="harness-dashboard">
      <h2>Harness Dashboard</h2>

      {/* Harness Flow Diagram */}
      <div className="flow-diagram">
        <h3>Harness Flow</h3>
        <div className="diagram">
          <div className="flow-box">Run Loop Start</div>
          <div className="flow-arrow">↓</div>
          <div className="flow-box">Find Incomplete Milestone</div>
          <div className="flow-arrow">↓</div>
          <div className="flow-box">Generate Code</div>
          <div className="flow-arrow">↓</div>
          <div className="flow-box">Review Code</div>
          <div className="flow-arrow">↓</div>
          <div className="flow-decision">Review Passed?</div>
          <div className="flow-split">
            <div className="flow-path">
              <span>Yes</span>
              <div className="flow-box">Mark Complete</div>
            </div>
            <div className="flow-path">
              <span>No</span>
              <div className="flow-box">Retry or Escalate</div>
            </div>
          </div>
        </div>
      </div>

      {/* Current Run Status */}
      {currentRun && (
        <div className="current-run">
          <h3>Current Run: {currentRun.run_id}</h3>
          <div className={`status status-${getRunStatus(currentRun)}`}>
            Status: {getRunStatus(currentRun)}
          </div>
          <div className="events">
            {currentRun.events.map((event, i) => (
              <div key={i} className="event">
                <span className="step">{event.step}</span>
                <span className={`status-badge status-${event.status}`}>{event.status}</span>
                <span className="timestamp">{formatTimestamp(event.timestamp)}</span>
                {event.detail && <div className="detail">{event.detail}</div>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Run Timeline */}
      <div className="run-timeline">
        <h3>Run History</h3>
        {runs.slice(0, 10).map((run) => (
          <div
            key={run.run_id}
            className={`timeline-item ${run === currentRun ? 'active' : ''}`}
          >
            <div className="run-header">
              <span className="run-id">{run.run_id}</span>
              <span className={`status-badge status-${getRunStatus(run)}`}>
                {getRunStatus(run)}
              </span>
            </div>
            <div className="run-time">{formatTimestamp(run.events[0]?.timestamp)}</div>
          </div>
        ))}
      </div>

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
        }

        .flow-diagram {
          background: #f5f5f5;
          padding: 1.5rem;
          border-radius: 8px;
          margin-bottom: 2rem;
        }

        .diagram {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 0.5rem;
        }

        .flow-box {
          padding: 0.75rem 1.5rem;
          background: white;
          border: 2px solid #0288d1;
          border-radius: 4px;
          font-weight: 500;
        }

        .flow-decision {
          padding: 0.75rem 1.5rem;
          background: #fff9c4;
          border: 2px solid #f57f17;
          border-radius: 4px;
          font-weight: 500;
        }

        .flow-arrow {
          font-size: 1.5rem;
          color: #888;
        }

        .flow-split {
          display: flex;
          gap: 2rem;
          margin-top: 0.5rem;
        }

        .flow-path {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 0.5rem;
        }

        .current-run {
          background: white;
          border: 1px solid #ddd;
          border-radius: 8px;
          padding: 1.5rem;
          margin-bottom: 2rem;
        }

        .status {
          display: inline-block;
          padding: 0.5rem 1rem;
          border-radius: 4px;
          font-weight: 600;
          margin-bottom: 1rem;
        }

        .status-completed { background: #c8e6c9; color: #1b5e20; }
        .status-in-progress { background: #bbdefb; color: #0d47a1; }
        .status-incomplete { background: #ffcdd2; color: #b71c1c; }
        .status-escalated { background: #ffe0b2; color: #e65100; }

        .events {
          display: flex;
          flex-direction: column;
          gap: 0.75rem;
        }

        .event {
          padding: 0.75rem;
          background: #f5f5f5;
          border-radius: 4px;
        }

        .step {
          font-weight: 600;
          margin-right: 0.5rem;
        }

        .status-badge {
          display: inline-block;
          padding: 0.25rem 0.5rem;
          border-radius: 3px;
          font-size: 0.875rem;
          margin-right: 0.5rem;
        }

        .status-started { background: #e1f5ff; color: #01579b; }
        .status-completed { background: #c8e6c9; color: #1b5e20; }
        .status-failed { background: #ffcdd2; color: #b71c1c; }

        .timestamp {
          color: #666;
          font-size: 0.875rem;
        }

        .detail {
          margin-top: 0.5rem;
          color: #444;
          font-size: 0.875rem;
        }

        .run-timeline {
          background: white;
          border: 1px solid #ddd;
          border-radius: 8px;
          padding: 1.5rem;
          margin-bottom: 2rem;
        }

        .timeline-item {
          padding: 0.75rem;
          border-left: 3px solid #ddd;
          margin-bottom: 0.75rem;
        }

        .timeline-item.active {
          border-left-color: #0288d1;
          background: #f5f5f5;
        }

        .run-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 0.25rem;
        }

        .run-id {
          font-family: monospace;
          font-size: 0.875rem;
        }

        .run-time {
          color: #666;
          font-size: 0.875rem;
        }

        .outstanding-issues {
          background: #fff3e0;
          border: 1px solid #f57c00;
          border-radius: 8px;
          padding: 1.5rem;
        }

        .issues-content {
          font-size: 0.875rem;
        }
      `}</style>
    </div>
  );
}
