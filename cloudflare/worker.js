/**
 * Science Pulse Edge Worker.
 *
 * Маршруты:
 *   GET  /tg-cdn/:file_id.png  — безопасный прокси картинки из Telegram CDN
 *   GET  /cards/*              — карточки из R2
 *   GET  /api/graph            — граф знаний из D1
 *   POST /api/ingest           — загрузка карточки + узла (Bearer INGEST_SECRET)
 *   POST /api/state            — реплика состояния (Bearer INGEST_SECRET)
 *   POST /api/state/lock       — lease-lock writer (Bearer INGEST_SECRET)
 *   POST /api/state/unlock     — освобождение lock (Bearer INGEST_SECRET)
 *   POST /telegram-webhook     — пульт: answerCallbackQuery + запуск GitHub Actions
 *   GET  /node/:id             — тот же index.html с og:image для соцсетей
 *
 * Секреты: TG_BOT_TOKEN, GH_PAT, GH_REPO, INGEST_SECRET.
 * Bindings: DB (D1), R2_BUCKET (R2).
 */

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, PUT, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
};

// Таблицы состояния, которые реплицируются из локального SQLite (/api/state).
const STATE_TABLES = ["posts", "publications", "metrics", "sources", "kv", "seen"];

// Монотонные правила слияния (CRDT Join-Semilattice) на стороне D1.
const STATUS_RANK = { ready: 1, publishing: 2, failed: 3, published: 4 };
const PUBLICATION_RANK = { error: 1, skipped: 1, failed: 2, ok: 3 };

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(handleScheduled(env, event));
  },

  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: CORS });
    }

    if (url.pathname === "/threads-callback" && request.method === "GET") {
      const code = url.searchParams.get("code");
      if (!code) return new Response("Threads OAuth: no code", { status: 400 });
      const appId = env.THREADS_APP_ID || "";
      const appSecret = env.THREADS_APP_SECRET || "";
      const redirectUri = env.THREADS_REDIRECT_URI || url.origin + "/threads-callback";
      if (!appId || !appSecret) return new Response("Threads OAuth: app id/secret missing", { status: 500 });
      try {
        const tokenResponse = await fetch("https://graph.threads.com/oauth/access_token", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: new URLSearchParams({
            client_id: appId,
            client_secret: appSecret,
            grant_type: "authorization_code",
            redirect_uri: redirectUri,
            code,
          }).toString(),
        });
        const short = await tokenResponse.json();
        if (!short.access_token) return new Response("Threads OAuth: " + JSON.stringify(short), { status: 400 });
        const longResponse = await fetch(
          "https://graph.threads.com/access_token?grant_type=th_exchange_token&client_secret=" +
          encodeURIComponent(appSecret) + "&access_token=" + encodeURIComponent(short.access_token)
        );
        const long = await longResponse.json();
        const token = long.access_token || short.access_token;
        const meResponse = await fetch(
          "https://graph.threads.com/v1.0/me?fields=id,username&access_token=" + encodeURIComponent(token)
        );
        const me = await meResponse.json();
        return new Response(JSON.stringify({
          ok: true,
          user_id: me.id || "",
          username: me.username || "",
          access_token: token,
          expires_in: long.expires_in || short.expires_in || 0,
        }), {
          headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", ...CORS },
        });
      } catch (error) {
        return new Response("Threads OAuth error: " + String(error), { status: 500 });
      }
    }

    if (url.pathname.startsWith("/tg-cdn/") && request.method === "GET") {
      return telegramCdn(request, env, ctx, url);
    }

    if (url.pathname.startsWith("/cards/") && request.method === "GET") {
      const key = url.pathname.slice(1);
      const object = await env.R2_BUCKET.get(key);
      if (!object) return new Response("Card Not Found", { status: 404 });
      return new Response(object.body, {
        headers: {
          "Content-Type": key.endsWith(".webp") ? "image/webp" : "image/png",
          "Cache-Control": "public, max-age=31536000, immutable",
          ...CORS,
        },
      });
    }

    if (url.pathname === "/api/graph" && request.method === "GET") {
      const { results } = await env.DB.prepare(
        `SELECT id, domain, title, hook, formula_latex AS formula,
                js_arrow_fn AS js_fn, pagerank, poincare_x AS x, poincare_y AS y,
                card_r2_url, source_url, created_at
         FROM knowledge_nodes ORDER BY created_at DESC LIMIT 500`
      ).all();
      return Response.json({ nodes: results, links: [] }, { headers: CORS });
    }

    if (url.pathname === "/api/ingest" && request.method === "POST") {
      const auth = request.headers.get("Authorization");
      if (auth !== `Bearer ${env.INGEST_SECRET}`) {
        return new Response("Unauthorized", { status: 401, headers: CORS });
      }
      const form = await request.formData();
      const meta = JSON.parse(form.get("meta"));
      const png = form.get("png");
      if (!png || !meta.id) {
        return new Response("Bad Request", { status: 400, headers: CORS });
      }

      const r2Key = `cards/${meta.id}.png`;
      await env.R2_BUCKET.put(r2Key, png.stream(), {
        httpMetadata: { contentType: "image/png" },
      });
      const cardUrl = `${url.origin}/${r2Key}`;

      await env.DB.prepare(
        `INSERT OR REPLACE INTO knowledge_nodes
         (id, domain, title, hook, body, formula_latex, js_arrow_fn, merkle_hash,
          pagerank, poincare_x, poincare_y, card_r2_url, source_url)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13)`
      )
        .bind(
          meta.id,
          meta.domain,
          meta.title,
          meta.hook || "",
          meta.body || "",
          meta.formula || "",
          meta.js_fn || "",
          meta.merkle_hash || "",
          meta.pagerank || 0.05,
          meta.poincare_x || 0,
          meta.poincare_y || 0,
          cardUrl,
          meta.source_url || ""
        )
        .run();

      return Response.json({ ok: true, card_url: cardUrl }, { headers: CORS });
    }

    if (url.pathname === "/api/state/lock" && request.method === "POST") {
      const auth = request.headers.get("Authorization");
      if (auth !== `Bearer ${env.INGEST_SECRET}`) {
        return new Response("Unauthorized", { status: 401, headers: CORS });
      }
      let body = {};
      try { body = await request.json(); } catch (_) { body = {}; }
      const owner = String(body.owner || "").trim().slice(0, 200);
      if (!owner) return Response.json({ ok: false, error: "owner required" }, { status: 400, headers: CORS });
      const ttl = Math.max(30, Math.min(3600, Number(body.ttl_s) || 900));
      const now = Math.floor(Date.now() / 1000);
      const expires = now + ttl;
      await env.DB.prepare(
        `CREATE TABLE IF NOT EXISTS state_lock (
           id INTEGER PRIMARY KEY CHECK (id = 1),
           owner TEXT NOT NULL,
           expires_at REAL NOT NULL
         )`
      ).run();
      const result = await env.DB.prepare(
        `INSERT INTO state_lock (id, owner, expires_at) VALUES (1, ?1, ?2)
         ON CONFLICT(id) DO UPDATE SET owner = excluded.owner, expires_at = excluded.expires_at
         WHERE state_lock.expires_at <= ?3`
      ).bind(owner, expires, now).run();
      const changes = Number((result.meta && result.meta.changes) || 0);
      if (changes > 0) {
        return Response.json({ ok: true, owner, expires_at: expires }, { headers: CORS });
      }
      const current = await env.DB.prepare(
        `SELECT owner, expires_at FROM state_lock WHERE id = 1`
      ).first();
      return Response.json({
        ok: false,
        locked: true,
        owner: current ? current.owner : "",
        expires_at: current ? current.expires_at : 0,
      }, { status: 409, headers: CORS });
    }

    if (url.pathname === "/api/state/unlock" && request.method === "POST") {
      const auth = request.headers.get("Authorization");
      if (auth !== `Bearer ${env.INGEST_SECRET}`) {
        return new Response("Unauthorized", { status: 401, headers: CORS });
      }
      let body = {};
      try { body = await request.json(); } catch (_) { body = {}; }
      const owner = String(body.owner || "").trim().slice(0, 200);
      if (!owner) return Response.json({ ok: false, error: "owner required" }, { status: 400, headers: CORS });
      const result = await env.DB.prepare(
        `DELETE FROM state_lock WHERE id = 1 AND owner = ?1`
      ).bind(owner).run();
      return Response.json({
        ok: true,
        released: Number((result.meta && result.meta.changes) || 0) > 0,
      }, { headers: CORS });
    }

    if (url.pathname === "/api/state" && request.method === "POST") {
      const auth = request.headers.get("Authorization");
      if (auth !== `Bearer ${env.INGEST_SECRET}`) {
        return new Response("Unauthorized", { status: 401, headers: CORS });
      }
      const body = await request.json();
      const tables = body.tables || {};
      let applied = 0;
      for (const [table, rows] of Object.entries(tables)) {
        if (!STATE_TABLES.includes(table) || !Array.isArray(rows)) continue;
        for (const row of rows) {
          const columns = Object.keys(row);
          if (!columns.length) continue;
          await applyMonotonic(env, table, row);
          const placeholders = columns.map((_, index) => `?${index + 1}`).join(", ");
          await env.DB.prepare(
            `INSERT OR REPLACE INTO ${table} (${columns.join(", ")}) VALUES (${placeholders})`
          )
            .bind(...columns.map((column) => row[column]))
            .run();
          applied += 1;
        }
      }
      return Response.json({ ok: true, applied }, { headers: CORS });
    }

    if (url.pathname === "/api/state" && request.method === "GET") {
      const full = url.searchParams.get("full") === "1";
      if (full) {
        const auth = request.headers.get("Authorization");
        if (auth !== `Bearer ${env.INGEST_SECRET}`) {
          return new Response("Unauthorized", { status: 401, headers: CORS });
        }
        const tables = {};
        for (const table of STATE_TABLES) {
          const { results } = await env.DB.prepare(`SELECT * FROM ${table}`).all();
          tables[table] = results || [];
        }
        return Response.json({ ok: true, tables }, { headers: CORS });
      }
      const counts = {};
      for (const table of STATE_TABLES) {
        const row = await env.DB.prepare(`SELECT COUNT(*) AS c FROM ${table}`).first();
        counts[table] = row ? row.c : 0;
      }
      return Response.json({ counts }, { headers: CORS });
    }

    if (url.pathname === "/telegram-webhook" && request.method === "POST") {
      const webhookSecret = env.TG_WEBHOOK_SECRET || "";
      if (webhookSecret && request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== webhookSecret) {
        return new Response("Unauthorized", { status: 401, headers: CORS });
      }
      const update = await request.json();
      if (update.message && update.message.text) {
        const text = String(update.message.text || "").trim();
        const chatId = update.message.chat && update.message.chat.id;
        if (text.startsWith("/run")) {
          await triggerGitHubRenderer(env, "run");
          await sendTelegram(env, chatId, "Принято: бужу фабрику (run).");
        } else if (text.startsWith("/status")) {
          await sendStatus(env, chatId);
        } else if (text.startsWith("/pause")) {
          await kvSet(env, "paused", "1");
          await sendTelegram(env, chatId, "Пауза включена: публикации остановлены.");
        } else if (text.startsWith("/resume")) {
          await kvSet(env, "paused", "0");
          await sendTelegram(env, chatId, "Пауза снята: публикации разрешены.");
        }
      }
      if (update.callback_query) {
        const callback = update.callback_query;
        await fetch(
          `https://api.telegram.org/bot${env.TG_BOT_TOKEN}/answerCallbackQuery`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              callback_query_id: callback.id,
              text: `Команда: ${callback.data || "auto"}`,
            }),
          }
        );
        await triggerGitHubRenderer(env, callback.data || "auto");
      }
      return new Response("OK", { headers: CORS });
    }

    if (url.pathname.startsWith("/node/") && request.method === "GET") {
      return nodeWithOpenGraph(request, env, url);
    }

    return new Response("Science Pulse Edge Active", { status: 200, headers: CORS });
  },
};

async function handleScheduled(env, event) {
  const now = new Date();
  const hour = now.getUTCHours();
  const slotHours = [6, 10, 14, 18];
  if (slotHours.includes(hour)) {
    try {
      await triggerGitHubRenderer(env, "run");
    } catch (error) {
      console.error("scheduled dispatch:", String(error));
    }
  }
  try {
    await checkSilence(env);
  } catch (error) {
    console.error("watchdog:", String(error));
  }
}

async function kvGet(env, key) {
  const row = await env.DB.prepare("SELECT value FROM kv WHERE key = ?1").bind(key).first();
  return row ? String(row.value || "") : "";
}

async function kvSet(env, key, value) {
  await env.DB.prepare("INSERT OR REPLACE INTO kv (key, value) VALUES (?1, ?2)")
    .bind(key, String(value))
    .run();
}

async function sendTelegram(env, chatId, text) {
  if (!env.TG_BOT_TOKEN || !chatId) return;
  await fetch(`https://api.telegram.org/bot${env.TG_BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text, disable_web_page_preview: true }),
  });
}

async function sendStatus(env, chatId) {
  if (!chatId) return;
  const last = await env.DB.prepare(
    "SELECT MAX(created_at) AS last FROM publications WHERE status = 'ok'"
  ).first();
  const ready = await env.DB.prepare("SELECT COUNT(*) AS c FROM posts WHERE status = 'ready'").first();
  const paused = await kvGet(env, "paused");
  const lastAt = last && last.last ? String(last.last) : "нет";
  await sendTelegram(
    env,
    chatId,
    `Science Pulse\nПоследняя публикация: ${lastAt}\nОчередь ready: ${ready ? ready.c : 0}\nПауза: ${paused === "1" ? "да" : "нет"}`
  );
}

async function checkSilence(env) {
  if (!env.TG_BOT_TOKEN || !env.TG_ADMIN_CHAT_ID) return;
  if ((await kvGet(env, "paused")) === "1") return;
  const row = await env.DB.prepare(
    "SELECT MAX(created_at) AS last FROM publications WHERE status = 'ok'"
  ).first();
  const lastAt = row && row.last ? String(row.last) : "";
  const lastMs = lastAt ? Date.parse(lastAt) : 0;
  const hours = lastMs ? (Date.now() - lastMs) / 3600000 : Infinity;
  if (hours < 8) return;
  const alertKey = "last_alert_at";
  const previous = Number(await kvGet(env, alertKey) || 0);
  if (previous && Date.now() - previous < 6 * 3600000) return;
  const critical = hours >= 36;
  if (critical) {
    try {
      await triggerGitHubRenderer(env, "run");
    } catch (error) {
      console.error("watchdog dispatch:", String(error));
    }
  }
  await sendTelegram(
    env,
    env.TG_ADMIN_CHAT_ID,
    critical
      ? `КРИТИЧНО: нет публикаций ${Math.round(hours)} ч. Пробую разбудить фабрику.`
      : `Тишина ${Math.round(hours)} ч: публикаций нет. Проверьте /status.`
  );
  await kvSet(env, alertKey, String(Date.now()));
}

async function telegramCdn(request, env, ctx, url) {
  const cache = caches.default;
  const cached = await cache.match(request);
  if (cached) return cached;

  const fileId = url.pathname.replace("/tg-cdn/", "").replace(".png", "");
  const metaResponse = await fetch(
    `https://api.telegram.org/bot${env.TG_BOT_TOKEN}/getFile?file_id=${encodeURIComponent(fileId)}`
  );
  const meta = await metaResponse.json();
  if (!meta.ok) return new Response("Image not found in Telegram CDN", { status: 404 });

  const imageResponse = await fetch(
    `https://api.telegram.org/file/bot${env.TG_BOT_TOKEN}/${meta.result.file_path}`
  );
  const upstreamType = imageResponse.headers.get("content-type") || "";
  const contentType = upstreamType.startsWith("image/") ? upstreamType : "image/jpeg";
  const response = new Response(imageResponse.body, {
    headers: {
      "Content-Type": contentType,
      "Cache-Control": "public, max-age=31536000, immutable",
      ...CORS,
    },
  });
  ctx.waitUntil(cache.put(request, response.clone()));
  return response;
}

async function nodeWithOpenGraph(request, env, url) {
  const nodeId = url.pathname.split("/node/")[1];
  const siteOrigin = env.SITE_ORIGIN || url.origin;
  const baseHtml = await fetch(`${siteOrigin}/index.html`).then((response) => response.text());
  const node = await env.DB.prepare(
    "SELECT title, body, card_r2_url FROM knowledge_nodes WHERE id = ?1"
  )
    .bind(nodeId)
    .first();
  if (!node) {
    return new Response(baseHtml, { headers: { "Content-Type": "text/html;charset=UTF-8" } });
  }
  const image = node.card_r2_url || `${siteOrigin}/cards/${nodeId}.png`;
  const injected = baseHtml.replace(
    "</head>",
    `<meta property="og:title" content="${escapeHtml(node.title)}">
     <meta property="og:description" content="${escapeHtml((node.body || "").slice(0, 160))}">
     <meta property="og:image" content="${image}">
     <meta name="twitter:card" content="summary_large_image">
     <script>window.INITIAL_NODE_ID = "${nodeId}";</script></head>`
  );
  return new Response(injected, { headers: { "Content-Type": "text/html;charset=UTF-8" } });
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function applyMonotonic(env, table, row) {
  // Монотонное слияние: старый статус не может затереть более сильный,
  // непустые поля не затираются пустыми.
  if (table === "posts") {
    const existing = await env.DB.prepare("SELECT * FROM posts WHERE id = ?1").bind(row.id).first();
    if (!existing) return;
    if ((STATUS_RANK[row.status] || 0) < (STATUS_RANK[existing.status] || 0)) {
      row.status = existing.status;
    }
    for (const column of ["card_file_id", "published_at", "card_path"]) {
      if (!row[column] && existing[column]) row[column] = existing[column];
    }
  } else if (table === "publications") {
    const existing = await env.DB.prepare(
      "SELECT * FROM publications WHERE post_id = ?1 AND platform = ?2"
    )
      .bind(row.post_id, row.platform)
      .first();
    if (!existing) return;
    if ((PUBLICATION_RANK[row.status] || 0) < (PUBLICATION_RANK[existing.status] || 0)) {
      row.status = existing.status;
    }
  }
}

async function triggerGitHubRenderer(env, command) {
  const response = await fetch(
    `https://api.github.com/repos/${env.GH_REPO}/actions/workflows/science_pulse.yml/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GH_PAT}`,
        Accept: "application/vnd.github+json",
        "User-Agent": "SciencePulse-Cloudflare-Edge",
      },
      body: JSON.stringify({ ref: "main", inputs: { command: command || "run" } }),
    }
  );
  return response;
}
