/**
 * Science Pulse: внешний будильник.
 *
 * Cloudflare Worker Cron будит GitHub Actions через workflow_dispatch.
 * Основной клиент — GitHub App installation token (1 час, без срока годности),
 * PAT остаётся только временным fallback. Каждый dispatch пишет пульс в D1 KV.
 */
const SLOT_HOURS = [6, 10, 14, 18];
const encoder = new TextEncoder();

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(runSlot(env));
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/run" && request.method === "POST") {
      if (env.TRIGGER_SECRET && request.headers.get("Authorization") !== `Bearer ${env.TRIGGER_SECRET}`) {
        return new Response("Unauthorized", { status: 401 });
      }
      const result = await dispatch(env, "run");
      return Response.json(result);
    }
    if (url.pathname === "/health") {
      const state = await readState(env);
      const kv = (state?.tables?.kv) || [];
      const get = (key) => (kv.find((row) => row.key === key) || {}).value || "";
      return Response.json({
        ok: true,
        worker: "science-pulse-cron",
        auth: authMode(env),
        alert_configured: Boolean(env.TG_BOT_TOKEN && env.TG_ADMIN_CHAT_ID),
        last_dispatch_at: Number(get("cron_last_dispatch_at")) || 0,
        last_dispatch_ok: get("cron_last_dispatch_ok") === "1",
        last_status: Number(get("cron_last_status")) || 0,
        last_error: get("cron_last_error") || "",
      });
    }
    return new Response("Science Pulse Cron Active", { status: 200 });
  },
};

function authMode(env) {
  if (env.GH_APP_ID && env.GH_APP_PRIVATE_KEY && env.GH_APP_INSTALLATION_ID) return "github_app";
  if (env.GH_PAT) return "pat_fallback";
  return "none";
}

async function runSlot(env) {
  const hour = new Date().getUTCHours();
  if (SLOT_HOURS.includes(hour)) {
    await dispatch(env, "run");
    return;
  }
  await checkSilence(env);
}

async function readState(env) {
  if (!env.DB) return null;
  const kv = await env.DB.prepare("SELECT key, value FROM kv").all();
  const pub = await env.DB.prepare(
    "SELECT created_at FROM publications WHERE status = 'ok' ORDER BY created_at DESC LIMIT 1"
  ).first();
  return {
    tables: {
      kv: kv.results || [],
      publications: pub ? [{ status: "ok", created_at: pub.created_at }] : [],
    },
  };
}

async function checkSilence(env) {
  const state = await readState(env);
  if (!state) return;
  const tables = state.tables || {};
  const pubs = tables.publications || [];
  let lastMs = 0;
  for (const row of pubs) {
    if (row.status !== "ok" || !row.created_at) continue;
    const ts = Date.parse(row.created_at);
    if (ts > lastMs) lastMs = ts;
  }
  const hours = lastMs ? (Date.now() - lastMs) / 3600000 : Infinity;
  if (hours < 8) return;
  const kv = tables.kv || [];
  const lastDispatch = Number((kv.find((x) => x.key === "cron_last_dispatch_at") || {}).value || 0);
  const lastOk = (kv.find((x) => x.key === "cron_last_dispatch_ok") || {}).value === "1";
  if (lastDispatch && lastOk && Date.now() - lastDispatch < 2 * 3600000) return;
  await dispatch(env, "run");
}

async function writePulse(env, result, mode) {
  const kv = [
    { key: "cron_last_dispatch_at", value: String(Date.now()) },
    { key: "cron_last_dispatch_ok", value: result.ok ? "1" : "0" },
    { key: "cron_last_status", value: String(result.status || 0) },
    { key: "cron_last_error", value: String(result.body || "").slice(0, 240) },
    { key: "cron_auth_mode", value: mode },
  ];
  if (env.DB) {
    const statement = env.DB.prepare(
      "INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)"
    );
    await env.DB.batch(kv.map((row) => statement.bind(row.key, row.value)));
  }
  if (!result.ok) await alert(env, `Science Pulse cron dispatch failed (${result.status}): ${String(result.body || "").slice(0, 160)}`);
}

async function alert(env, text) {
  if (!env.TG_BOT_TOKEN || !env.TG_ADMIN_CHAT_ID) return;
  try {
    await fetch(`https://api.telegram.org/bot${env.TG_BOT_TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: env.TG_ADMIN_CHAT_ID, text, parse_mode: "HTML" }),
    });
  } catch (error) {
    console.error("alert failed", String(error));
  }
}

function b64url(bytes) {
  let text = "";
  for (const byte of bytes) text += String.fromCharCode(byte);
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function appJwt(appId, pkcs8Pem) {
  const pem = String(pkcs8Pem).replace(/-----[^-]+-----|\s/g, "");
  const der = Uint8Array.from(atob(pem), (char) => char.charCodeAt(0));
  const key = await crypto.subtle.importKey(
    "pkcs8", der,
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false, ["sign"],
  );
  const now = Math.floor(Date.now() / 1000);
  const header = b64url(encoder.encode(JSON.stringify({ alg: "RS256", typ: "JWT" })));
  const payload = b64url(encoder.encode(JSON.stringify({
    iat: now - 60,
    exp: now + 540,
    iss: String(appId),
  })));
  const signature = await crypto.subtle.sign(
    { name: "RSASSA-PKCS1-v1_5" },
    key,
    encoder.encode(`${header}.${payload}`),
  );
  return `${header}.${payload}.${b64url(new Uint8Array(signature))}`;
}

async function githubToken(env) {
  const mode = authMode(env);
  if (mode === "github_app") {
    const jwt = await appJwt(env.GH_APP_ID, env.GH_APP_PRIVATE_KEY);
    const response = await fetch(
      `https://api.github.com/app/installations/${env.GH_APP_INSTALLATION_ID}/access_tokens`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${jwt}`,
          Accept: "application/vnd.github+json",
          "User-Agent": "SciencePulse-Cron-Worker",
        },
      },
    );
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.token) {
      throw new Error(`app token ${response.status}: ${String(data.message || "")}`);
    }
    return { token: data.token, mode };
  }
  if (mode === "pat_fallback") return { token: env.GH_PAT, mode };
  throw new Error("no GitHub credentials configured");
}

async function dispatch(env, command) {
  if (!env.GH_REPO) {
    const result = { ok: false, status: 500, body: "GH_REPO missing", mode: authMode(env) };
    await writePulse(env, result, result.mode);
    return result;
  }
  let auth;
  try {
    auth = await githubToken(env);
  } catch (error) {
    const result = { ok: false, status: 401, body: String(error), mode: authMode(env) };
    await writePulse(env, result, result.mode);
    return result;
  }
  const response = await fetch(
    `https://api.github.com/repos/${env.GH_REPO}/actions/workflows/science_pulse.yml/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${auth.token}`,
        Accept: "application/vnd.github+json",
        "User-Agent": "SciencePulse-Cron-Worker",
      },
      body: JSON.stringify({ ref: "main", inputs: { command: command || "run" } }),
    },
  );
  const body = await response.text();
  const result = { ok: response.status === 204, status: response.status, body, mode: auth.mode };
  await writePulse(env, result, auth.mode);
  return result;
}
