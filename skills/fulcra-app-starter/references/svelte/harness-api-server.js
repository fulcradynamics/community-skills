import { env } from '$env/dynamic/public';
import { error, json } from '@sveltejs/kit';
import { FulcraAPI } from '$lib/api-client.js';

/**
 * Server-side endpoints for harness dashboard
 *
 * Place at: src/routes/api/harness/
 * Create two files:
 * - runs/+server.js
 * - issues/+server.js
 */

// runs/+server.js
export async function GET_runs({ cookies, url }) {
  const accessToken = cookies.get('fulcra_access_token');

  if (!accessToken) {
    throw error(401, 'Not authenticated');
  }

  const annotationId = url.searchParams.get('annotation_id');
  const startDate = url.searchParams.get('start_date') || '2026-09-01';
  const endDate = url.searchParams.get('end_date') || '2026-09-30';

  if (!annotationId) {
    throw error(400, 'annotation_id parameter required');
  }

  try {
    const apiClient = new FulcraAPI(env.PUBLIC_FULCRA_API_ENDPOINT, accessToken);
    const dataType = annotationId.replace('/', '%2F');
    const records = await apiClient.get(`v1/records/${dataType}?start_date=${startDate}&end_date=${endDate}`);
    return json(records);
  } catch (err) {
    console.error('Error fetching harness runs:', err);
    // Return empty result if no data exists yet
    if (err.message?.includes('404')) {
      return json({ records: [] });
    }
    throw error(500, err.message || 'Failed to fetch harness runs');
  }
}

// issues/+server.js
export async function GET_issues({ cookies, url }) {
  const accessToken = cookies.get('fulcra_access_token');

  if (!accessToken) {
    throw error(401, 'Not authenticated');
  }

  const workspacePath = url.searchParams.get('workspace_path');

  if (!workspacePath) {
    throw error(400, 'workspace_path parameter required');
  }

  try {
    const apiClient = new FulcraAPI(env.PUBLIC_FULCRA_API_ENDPOINT, accessToken);
    const content = await apiClient.get(`files/${workspacePath}/outstanding-issues.md`);
    return new Response(content, {
      headers: { 'Content-Type': 'text/plain' }
    });
  } catch (err) {
    // Return empty string if file doesn't exist (expected for 404)
    if (err.message?.includes('404')) {
      return new Response('', {
        headers: { 'Content-Type': 'text/plain' }
      });
    }
    console.error('Error fetching outstanding issues:', err);
    return new Response('', {
      headers: { 'Content-Type': 'text/plain' }
    });
  }
}
