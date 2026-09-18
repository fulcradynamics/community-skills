import { env as publicEnv } from '$env/dynamic/public';
import { env as privateEnv } from '$env/dynamic/private';

/**
 * Ownership check for the harness dashboard.
 *
 * The owner's Fulcra user id lives in the server-only OWNER_USER_ID env var
 * (no PUBLIC_ prefix), so it is never shipped to the browser. We resolve the
 * *current* user's id from the Auth0 userinfo endpoint — the same
 * `fulcradynamics.com/userid` claim the client used to read — using the access
 * token from the HTTP-only cookie, then compare the two server-side.
 *
 * @param {string | undefined} accessToken - Fulcra access token from the cookie.
 * @returns {Promise<boolean>} true only when the caller is the configured owner.
 */
export async function isOwner(accessToken) {
  const ownerId = privateEnv.OWNER_USER_ID;
  if (!accessToken || !ownerId) return false;

  try {
    const res = await fetch(`https://${publicEnv.PUBLIC_AUTH0_DOMAIN}/userinfo`, {
      headers: { Authorization: `Bearer ${accessToken}` }
    });
    if (!res.ok) return false;
    const info = await res.json();
    return info['fulcradynamics.com/userid'] === ownerId;
  } catch {
    return false;
  }
}
