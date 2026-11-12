/**
 * Science Pulse: внешний будильник.
 *
 * Cloudflare Worker Cron вызывает GitHub Actions workflow_dispatch в слоты
 * 06/10/14/18 UTC. Не хранит состояние и не публикует сам — только будит
 * основной конвейер. Это обходит ненадёжный GitHub Actions schedule.
 */
const SLOT_HOURS = [6, 10, 14, 18];

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
      return Response.json({ ok: result.ok, status: result.status });
    }
    if (url.pathname === "/health") {
      return Response.json({ ok: true, worker: "science-pulse-cron" });
    }
    return new Response("Science Pulse Cron Active", { status: 200 });
  },
};

async function runSlot(env) {
  const hour = new Date().getUTCHours();
  if (SLOT_HOURS.includes(hour)) {
    const result = await dispatch(env, "run");
    if (!result.ok) console.error("dispatch failed", result.status, result.body);
    return;
  }
  await checkSilence(env);
}

async function stateRequest(env, method, body) {
  if (!env.CF_WORKER_URL || !env.INGEST_SECRET) return null;
  const url = `${env.CF_WORKER_URL.replace(/\/$/, "")}/api/state${method === "GET" ? "?full=1" : ""}`;
  const response = await fetch(url, {
    method,
    headers: {
      Authorization: `Bearer ${env.INGEST_SECRET}`,
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) return null;
  return method === "GET" ? response.json() : response.json().catch(() => ({}));
}

async function checkSilence(env) {
  const state = await stateRequest(env, "GET");
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
  if (lastDispatch && Date.now() - lastDispatch < 2 * 3600000) return;
  const result = await dispatch(env, "run");
  await stateRequest(env, "POST", {
    tables: { kv: [{ key: "cron_last_dispatch_at", value: String(Date.now()) }] },
  });
  if (!result.ok) console.error("silence dispatch failed", result.status, result.body);
}

async function dispatch(env, command) {
  if (!env.GH_PAT || !env.GH_REPO) {
    return { ok: false, status: 500, body: "GH_PAT/GH_REPO missing" };
  }
  const response = await fetch(
    `https://api.github.com/repos/${env.GH_REPO}/actions/workflows/science_pulse.yml/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GH_PAT}`,
        Accept: "application/vnd.github+json",
        "User-Agent": "SciencePulse-Cron-Worker",
      },
      body: JSON.stringify({ ref: "main", inputs: { command: command || "run" } }),
    }
  );
  return { ok: response.status === 204, status: response.status, body: await response.text() };
}
