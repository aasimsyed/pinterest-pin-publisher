/**
 * pinterest-pin-publisher Worker
 *
 * Runs on a Cron Trigger (see wrangler.toml). Each run:
 *   1. Makes sure we have a valid Pinterest access token (refreshing via
 *      OAuth if the cached one is expired).
 *   2. Queries D1 for pins whose publish_at has arrived and are still
 *      "pending".
 *   3. POSTs each one to Pinterest's v5 Create Pin endpoint.
 *   4. Marks each row published/failed in D1.
 *
 * Pinterest's v5 API has no native "scheduled_at" field -- it publishes
 * immediately on request. This Worker is what turns "publish immediately"
 * into "publish on schedule": it only calls the API once a row's
 * publish_at time has actually arrived.
 */

const PINTEREST_API_BASE = "https://api.pinterest.com/v5";
const PINTEREST_TOKEN_URL = "https://api.pinterest.com/v5/oauth/token";

// How many rows to publish per cron tick. Keep this modest -- Pinterest
// rate-limits pin creation per app/user, and publishing everything at once
// defeats the point of spreading posts across the day.
const BATCH_SIZE = 5;

// Refresh the access token if it expires within this many seconds, so we
// never try to use a token that dies mid-request.
const TOKEN_REFRESH_BUFFER_SECONDS = 300;

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(runPublishCycle(env));
  },

  // Optional manual trigger for testing locally with `wrangler dev`, e.g.:
  //   curl -H "Authorization: Bearer $MANUAL_TRIGGER_SECRET" https://.../run
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname !== "/run") {
      return new Response("Not found", { status: 404 });
    }
    const auth = request.headers.get("Authorization") || "";
    if (auth !== `Bearer ${env.MANUAL_TRIGGER_SECRET}`) {
      return new Response("Unauthorized", { status: 401 });
    }
    const result = await runPublishCycle(env);
    return new Response(JSON.stringify(result, null, 2), {
      headers: { "content-type": "application/json" },
    });
  },
};

async function runPublishCycle(env) {
  const accessToken = await getValidAccessToken(env);
  const nowIso = new Date().toISOString();

  const due = await env.DB.prepare(
    `SELECT * FROM pin_queue
     WHERE status = 'pending' AND publish_at <= ?
     ORDER BY publish_at ASC
     LIMIT ?`
  )
    .bind(nowIso, BATCH_SIZE)
    .all();

  const results = [];
  for (const row of due.results) {
    const outcome = await publishPin(env, accessToken, row);
    results.push({ id: row.id, title: row.title, ...outcome });
  }

  return { checked_at: nowIso, published: results.length, results };
}

async function publishPin(env, accessToken, row) {
  const body = {
    title: row.title,
    description: row.description || undefined,
    link: row.link || undefined,
    board_id: row.board_id,
    media_source: {
      source_type: "image_url",
      url: row.media_url,
    },
  };

  const response = await fetch(`${PINTEREST_API_BASE}/pins`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

  const payload = await response.json().catch(() => ({}));

  if (response.ok) {
    await env.DB.prepare(
      `UPDATE pin_queue
       SET status = 'published', pinterest_pin_id = ?, published_at = ?, error_message = NULL
       WHERE id = ?`
    )
      .bind(payload.id || null, new Date().toISOString(), row.id)
      .run();
    return { status: "published", pinterest_pin_id: payload.id };
  }

  const errorMessage = JSON.stringify(payload).slice(0, 500);
  await env.DB.prepare(
    `UPDATE pin_queue SET status = 'failed', error_message = ? WHERE id = ?`
  )
    .bind(errorMessage, row.id)
    .run();
  return { status: "failed", error: errorMessage, http_status: response.status };
}

async function getValidAccessToken(env) {
  const cached = await env.DB.prepare(
    `SELECT access_token, expires_at FROM oauth_tokens WHERE id = 1`
  ).first();

  if (cached) {
    const expiresAt = new Date(cached.expires_at).getTime();
    const bufferMs = TOKEN_REFRESH_BUFFER_SECONDS * 1000;
    if (expiresAt - Date.now() > bufferMs) {
      return cached.access_token;
    }
  }

  return refreshAccessToken(env);
}

async function refreshAccessToken(env) {
  const basicAuth = btoa(`${env.PINTEREST_CLIENT_ID}:${env.PINTEREST_CLIENT_SECRET}`);

  const response = await fetch(PINTEREST_TOKEN_URL, {
    method: "POST",
    headers: {
      Authorization: `Basic ${basicAuth}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: env.PINTEREST_REFRESH_TOKEN,
    }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Pinterest token refresh failed (${response.status}): ${text}`);
  }

  const data = await response.json();
  const expiresAt = new Date(Date.now() + data.expires_in * 1000).toISOString();

  await env.DB.prepare(
    `INSERT INTO oauth_tokens (id, access_token, expires_at)
     VALUES (1, ?, ?)
     ON CONFLICT(id) DO UPDATE SET access_token = excluded.access_token,
                                    expires_at = excluded.expires_at`
  )
    .bind(data.access_token, expiresAt)
    .run();

  return data.access_token;
}
