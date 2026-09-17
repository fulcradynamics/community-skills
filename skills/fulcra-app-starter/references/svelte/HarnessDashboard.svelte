<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { env } from '$env/dynamic/public';

  import { user } from '$lib/user';

  // Environment variables (set in .env)
  const OWNER_USER_ID = env.PUBLIC_OWNER_USER_ID;
  const HARNESS_ANNOTATION_ID = env.PUBLIC_HARNESS_ANNOTATION_ID;
  const WORKSPACE_PATH = env.PUBLIC_WORKSPACE_PATH;

  let runs: any[] = [];
  let currentRun: any = null;
  let outstandingIssues: string = '';
  let refreshInterval: any;

  // Check if current user is owner
  $: userId = $user.auth0UserInfo?.['fulcradynamics.com/userid'];
  $: isOwner = userId === OWNER_USER_ID;

  // Flow chart lookups for the currently selected run
  $: stepMap = new Map((currentRun?.events || []).map((e: any) => [e.step, e]));
  const hasStep = (step: string) => stepMap.has(step);
  const getStep = (step: string) => stepMap.get(step);

  // Which branches of the constant flow chart this run actually took.
  // The Nurse health-check at the top acts on the *previous* run, so a fix or
  // escalation appearing in this run means the nurse intervened before the run.
  $: nurseIntervened = stepMap.has('FIX_ATTEMPT') || stepMap.has('ESCALATE');
  $: projectComplete = stepMap.has('FIND_MILESTONE') && !stepMap.has('GENERATE');
  $: reviewFailed =
    stepMap.has('REVIEW') &&
    !stepMap.has('MARK_COMPLETE') &&
    (stepMap.has('RUN_COMPLETE') || stepMap.has('RUN_INCOMPLETE'));
  // Retries remaining => milestone left incomplete but the run still completes.
  $: retryScheduled = reviewFailed && stepMap.has('RUN_COMPLETE');

  async function fetchRuns() {
    try {
      // Fetch records from backend API
      const res = await fetch(`/api/harness/runs?annotation_id=${encodeURIComponent(HARNESS_ANNOTATION_ID)}&start_date=2026-09-01&end_date=2026-09-30`);
      const data = await res.json();

      // Extract records from the response
      const records = data.records || data || [];

      // Group by run_id from the record data
      const runMap = new Map();
      records.forEach((record: any) => {

        // Parse the note field as JSON to get harness data
        let harnessData;
        try {
          harnessData = record.note ? JSON.parse(record.note) : {};
        } catch (e) {
          console.error('Failed to parse note as JSON:', record.note);
          return;
        }

        const runId = harnessData.run_id;
        const step = harnessData.step;
        const status = harnessData.status;
        const detail = harnessData.detail || '';
        const timestamp = record.recorded_at;

        if (!runId || !step) return; // Skip records without required fields

        if (!runMap.has(runId)) {
          runMap.set(runId, { run_id: runId, events: [] });
        }
        runMap.get(runId).events.push({ step, status, timestamp, detail });
      });

      runs = Array.from(runMap.values()).sort((a, b) => {
        const aTime = a.events[0]?.timestamp || '';
        const bTime = b.events[0]?.timestamp || '';
        return bTime.localeCompare(aTime);
      });

      // Preserve the user's selection across polls; only default to the
      // latest run when nothing is selected yet or the selection disappeared.
      const selectedId = currentRun?.run_id;
      currentRun = runs.find((r) => r.run_id === selectedId) || runs[0] || null;
    } catch (e) {
      console.error('Failed to fetch runs:', e);
      runs = [];
      currentRun = null;
    }
  }

  async function fetchOutstandingIssues() {
    try {
      const res = await fetch(`/api/harness/issues?workspace_path=${encodeURIComponent(WORKSPACE_PATH)}`);
      outstandingIssues = await res.text();
    } catch (e) {
      outstandingIssues = '';
    }
  }

  onMount(async () => {
    // User should already be initialized by the main layout
    // Just check if owner and fetch data
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

    <!-- Run History - compact, scrollable -->
    <div class="run-history">
      <h3>Recent Runs</h3>
      <div class="run-list">
        {#each runs.slice(0, 3) as run}
          <button
            class="run-item"
            class:active={run === currentRun}
            on:click={() => currentRun = run}
          >
            <div class="run-header">
              <span class="run-id">{run.run_id}</span>
              <span class="status-badge status-{getRunStatus(run)}">{getRunStatus(run)}</span>
            </div>
            <div class="run-time">{formatTimestamp(run.events[0]?.timestamp)}</div>
          </button>
        {/each}
      </div>
    </div>

    <!-- Current Run with Flow Diagram -->
    {#if currentRun}
      <div class="current-run-flow">
        <div class="current-run-header">
          <h3>Run: {currentRun.run_id}</h3>
          <span class="run-status status-{getRunStatus(currentRun)}">{getRunStatus(currentRun)}</span>
        </div>

        {#snippet stepBox(key, name, extra = '')}
          <div class="flow-step-box {extra}" class:active={hasStep(key)}>
            <div class="step-header">
              <span class="step-name">{name}</span>
              {#if hasStep(key)}
                <span class="status-badge status-{getStep(key).status}">{getStep(key).status}</span>
              {/if}
            </div>
            {#if hasStep(key) && getStep(key).detail}
              <div class="step-detail">{getStep(key).detail}</div>
            {/if}
          </div>
        {/snippet}

        <div class="flow-chart">
          <!-- Nurse pre-check: runs before the main loop; escalation ends the loop -->
          <div class="flow-row nurse-band">
            <div class="flow-terminal start">Run Start</div>
            <div class="flow-h-arrow">→</div>
            <div class="flow-decision-box nurse inline">
              <div class="decision-text">🩺 Previous run completed?</div>
            </div>
            <div class="flow-h-arrow labeled">No →</div>
            <div class="flow-decision-box nurse inline">
              <div class="decision-text">🩺 Fix attempts remain?</div>
            </div>
            <div class="branch-col">
              <div class="branch-item" class:active={hasStep('FIX_ATTEMPT')}>
                <span class="branch-tag">Yes</span>
                {@render stepBox('FIX_ATTEMPT', '🩺 Attempt Fix', 'small')}
              </div>
              <div class="branch-item" class:active={hasStep('ESCALATE')}>
                <span class="branch-tag">No</span>
                {@render stepBox('ESCALATE', '🩺 Escalate', 'small')}
                <div class="flow-terminal escalated small">Loop Ends</div>
              </div>
            </div>
          </div>
          <div class="flow-arrow">↓</div>
          <div class="flow-passthrough">Previous run healthy or fixed — begin harness run</div>
          <div class="flow-arrow">↓</div>

          <!-- Milestone selection -->
          <div class="flow-row">
            {@render stepBox('FIND_MILESTONE', '🎛️ Find Incomplete Milestone', 'small')}
            <div class="flow-h-arrow">→</div>
            <div class="flow-decision-box inline">
              <div class="decision-text">🎛️ Any incomplete milestone?</div>
            </div>
            <div class="flow-h-arrow labeled">No →</div>
            <div class="branch-item" class:active={projectComplete}>
              <div class="flow-terminal complete small">Project Complete</div>
            </div>
          </div>
          <div class="flow-arrow">↓</div>

          {@render stepBox('GENERATE', '✍️ Generate Code')}
          <div class="flow-arrow">↓</div>
          {@render stepBox('REVIEW', '⚖️ Review Code')}
          <div class="flow-arrow">↓</div>

          <div class="flow-decision-box">
            <div class="decision-text">🎛️ Review passed?</div>
          </div>
          <div class="flow-split">
            <!-- Yes: milestone complete -->
            <div class="flow-path" class:active={hasStep('MARK_COMPLETE')}>
              <div class="path-label">Yes</div>
              {@render stepBox('MARK_COMPLETE', '🎛️ Mark Milestone Complete', 'small')}
              <div class="flow-arrow">↓</div>
              <div class="flow-terminal complete small">Run Complete</div>
            </div>
            <!-- No: retry or exhaust -->
            <div class="flow-path" class:active={reviewFailed}>
              <div class="path-label">No</div>
              <div class="flow-decision-box small">
                <div class="decision-text">🎛️ Retries remain?</div>
              </div>
              <div class="flow-split tight">
                <div class="flow-path" class:active={retryScheduled}>
                  <div class="path-label">Yes</div>
                  <div class="flow-terminal retry small">Leave Incomplete — Retry Next Run</div>
                </div>
                <div class="flow-path" class:active={hasStep('RUN_INCOMPLETE')}>
                  <div class="path-label">No</div>
                  <div class="flow-terminal incomplete small">End Run — Incomplete</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    {/if}

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

  .status-completed { background: var(--color-fulcra-teal-10); color: var(--color-fulcra-green-100); }
  .status-in-progress { background: var(--color-fulcra-lavender-25); color: var(--color-fulcra-purple-100); }
  .status-incomplete { background: #ffcdd2; color: var(--color-fulcra-error); }
  .status-escalated { background: #ffe0b2; color: #e65100; }

  .flow-chart {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0;
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

  .flow-terminal.start {
    background: var(--color-fulcra-black);
    color: var(--color-fulcra-white);
    border-color: var(--color-fulcra-black);
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

  .flow-terminal.escalated {
    background: #ffe0b2;
    border-color: #f57c00;
    color: #e65100;
  }

  .flow-passthrough {
    font-size: 0.8rem;
    font-style: italic;
    color: var(--color-fulcra-gray);
    padding: 0.5rem 0;
  }

  .flow-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: center;
    gap: 0.75rem;
    width: 100%;
    max-width: 900px;
  }

  .nurse-band {
    background: #fff8f0;
    border: 1px dashed #f57c00;
    border-radius: 10px;
    padding: 0.75rem;
  }

  .flow-row .flow-step-box,
  .branch-col .flow-step-box {
    width: auto;
    max-width: 230px;
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
    max-width: 210px;
    padding: 0.6rem 0.9rem;
    margin: 0;
  }

  .flow-decision-box.inline .decision-text {
    font-size: 0.85rem;
  }

  .branch-col {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .branch-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.25rem;
    opacity: 0.3;
    transition: opacity 0.2s;
  }

  .branch-item.active {
    opacity: 1;
  }

  .branch-tag {
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--color-fulcra-gray);
  }

  .flow-split {
    display: flex;
    gap: 2rem;
    margin: 1rem 0;
    width: 100%;
    max-width: 800px;
    justify-content: center;
  }

  .flow-split.tight {
    gap: 1rem;
    margin: 0.5rem 0 0;
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

  .status-started { background: var(--color-fulcra-lavender-50); color: var(--color-fulcra-purple-100); }
  .status-completed { background: var(--color-fulcra-teal-50); color: var(--color-fulcra-green-100); }
  .status-failed { background: #ffcdd2; color: var(--color-fulcra-error); }

  .step-detail {
    color: var(--color-fulcra-black);
    font-size: 0.875rem;
    margin-bottom: 0.5rem;
    line-height: 1.5;
  }

  .step-time {
    color: var(--color-fulcra-gray);
    font-size: 0.75rem;
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
</style>
