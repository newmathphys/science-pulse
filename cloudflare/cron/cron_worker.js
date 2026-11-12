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
  if (!SLOT_HOURS.includes(hour)) return;
  const result = await dispatch(env, "run");
  if (!result.ok) console.error("dispatch failed", result.status, result.body);
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
