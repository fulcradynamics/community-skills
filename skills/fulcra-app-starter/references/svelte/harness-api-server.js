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
  // Default to a rolling 30-day window ending today when the client omits dates.
  const now = new Date();
  const startDate =
    url.searchParams.get('start_date') ||
    new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
  const endDate = url.searchParams.get('end_date') || now.toISOString().slice(0, 10);

  if (!annotationId) {
    throw error(400, 'annotation_id parameter required');
  }

  try {
    const apiClient = new FulcraAPI(env.PUBLIC_FULCRA_API_ENDPOINT, accessToken);
    // See API docs: https://docs.fulcradynamics.com/rest-api/
    // GET /data/v1alpha1/event/{data_type}?start_time=<ISO8601>&end_time=<ISO8601>
    const dataType = annotationId.replace('/', '%2F');
    const records = await apiClient.get(`data/v1alpha1/event/${dataType}?start_time=${startDate}T00:00:00Z&end_time=${endDate}T23:59:59Z`);
    return json(records);
  } catch (err) {
    console.error('Error fetching harness runs:', err);
    // No data yet for this annotation
    if (err.message?.includes('404')) {
      return json({ records: [] });
    }
    // Expired/invalid token: surface as 401 so the client can re-authenticate
    if (err.message?.includes('401')) {
      throw error(401, 'Session expired — please sign in again');
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
