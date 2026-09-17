<script lang="ts">
  import { onMount, onDestroy } from 'svelte';

  // Environment variables (set in .env)
  const OWNER_USER_ID = import.meta.env.PUBLIC_OWNER_USER_ID;
  const HARNESS_ANNOTATION_ID = import.meta.env.PUBLIC_HARNESS_ANNOTATION_ID;
  const WORKSPACE_PATH = import.meta.env.PUBLIC_WORKSPACE_PATH;
  const FULCRA_API_URL = import.meta.env.PUBLIC_FULCRA_API_URL;

  let currentUser: any = null;
  let runs: any[] = [];
  let currentRun: any = null;
  let outstandingIssues: string = '';
  let refreshInterval: any;

  // Check if current user is owner
  $: isOwner = currentUser?.id === OWNER_USER_ID;

  async function fetchCurrentUser() {
    const res = await fetch(`${FULCRA_API_URL}/me`);
    currentUser = await res.json();
  }

  async function fetchRuns() {
    const res = await fetch(`${FULCRA_API_URL}/annotations/${HARNESS_ANNOTATION_ID}/records`);
    const records = await res.json();

    // Group by run_id and build timeline
    const runMap = new Map();
    records.forEach((r: any) => {
      if (!runMap.has(r.run_id)) {
        runMap.set(r.run_id, { run_id: r.run_id, events: [] });
      }
      runMap.get(r.run_id).events.push(r);
    });

    runs = Array.from(runMap.values()).sort((a, b) => {
      const aTime = a.events[0]?.timestamp || '';
      const bTime = b.events[0]?.timestamp || '';
      return bTime.localeCompare(aTime);
    });

    currentRun = runs[0] || null;
  }

  async function fetchOutstandingIssues() {
    try {
      const res = await fetch(`${FULCRA_API_URL}/files/${WORKSPACE_PATH}/outstanding-issues.md`);
      outstandingIssues = await res.text();
    } catch (e) {
      outstandingIssues = '';
    }
  }

  onMount(async () => {
    await fetchCurrentUser();
    if (isOwner) {
      await fetchRuns();
      await fetchOutstandingIssues();

      // Refresh every 5 seconds
      refreshInterval = setInterval(async () => {
        await fetchRuns();
        await fetchOutstandingIssues();
      }, 5000);
    }
  });

  onDestroy(() => {
    if (refreshInterval) clearInterval(refreshInterval);
  });

  function getRunStatus(run: any) {
    const lastEvent = run.events[run.events.length - 1];
    if (lastEvent.step === 'RUN_COMPLETE') return 'completed';
    if (lastEvent.step === 'RUN_INCOMPLETE') return 'incomplete';
    if (lastEvent.step === 'ESCALATE') return 'escalated';
    return 'in-progress';
  }

  function formatTimestamp(ts: string) {
    return new Date(ts).toLocaleString();
  }
</script>

{#if isOwner}
  <div class="harness-dashboard">
    <h2>Harness Dashboard</h2>

    <!-- Harness Flow Diagram -->
    <div class="flow-diagram">
      <h3>Harness Flow</h3>
      <div class="diagram">
        <div class="flow-box">Run Loop Start</div>
        <div class="flow-arrow">↓</div>
        <div class="flow-box">Find Incomplete Milestone</div>
        <div class="flow-arrow">↓</div>
        <div class="flow-box">Generate Code</div>
        <div class="flow-arrow">↓</div>
        <div class="flow-box">Review Code</div>
        <div class="flow-arrow">↓</div>
        <div class="flow-decision">Review Passed?</div>
        <div class="flow-split">
          <div class="flow-path">
            <span>Yes</span>
            <div class="flow-box">Mark Complete</div>
          </div>
          <div class="flow-path">
            <span>No</span>
            <div class="flow-box">Retry or Escalate</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Current Run Status -->
    {#if currentRun}
      <div class="current-run">
        <h3>Current Run: {currentRun.run_id}</h3>
        <div class="status status-{getRunStatus(currentRun)}">
          Status: {getRunStatus(currentRun)}
        </div>
        <div class="events">
          {#each currentRun.events as event}
            <div class="event">
              <span class="step">{event.step}</span>
              <span class="status-badge status-{event.status}">{event.status}</span>
              <span class="timestamp">{formatTimestamp(event.timestamp)}</span>
              {#if event.detail}
                <div class="detail">{event.detail}</div>
              {/if}
            </div>
          {/each}
        </div>
      </div>
    {/if}

    <!-- Run Timeline -->
    <div class="run-timeline">
      <h3>Run History</h3>
      {#each runs.slice(0, 10) as run}
        <div class="timeline-item" class:active={run === currentRun}>
          <div class="run-header">
            <span class="run-id">{run.run_id}</span>
            <span class="status-badge status-{getRunStatus(run)}">{getRunStatus(run)}</span>
          </div>
          <div class="run-time">{formatTimestamp(run.events[0]?.timestamp)}</div>
        </div>
      {/each}
    </div>

    <!-- Outstanding Issues -->
    {#if outstandingIssues}
      <div class="outstanding-issues">
        <h3>Outstanding Issues</h3>
        <div class="issues-content">{@html outstandingIssues}</div>
      </div>
    {/if}
  </div>
{/if}

<style>
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
</style>
