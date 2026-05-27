export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return jsonResponse({ error: "Method not allowed" }, 405);
    }

    const providedSecret = request.headers.get("x-webhook-secret");
    if (!providedSecret || providedSecret !== env.WEBHOOK_SECRET) {
      return jsonResponse({ error: "Unauthorized" }, 401);
    }

    let payload = {};
    try {
      const contentType = request.headers.get("content-type") || "";
      if (contentType.includes("application/json")) {
        payload = await request.json();
      }
    } catch {
      return jsonResponse({ error: "Invalid JSON payload" }, 400);
    }

    const githubResponse = await fetch(
      `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/dispatches`,
      {
        method: "POST",
        headers: {
          Accept: "application/vnd.github+json",
          Authorization: `Bearer ${env.GITHUB_TOKEN}`,
          "Content-Type": "application/json",
          "User-Agent": "notion-date-gap-sync-worker",
        },
        body: JSON.stringify({
          event_type: "notion-date-gap-sync",
          client_payload: {
            source: "cloudflare-worker",
            received_at: new Date().toISOString(),
            webhook_payload: payload,
          },
        }),
      },
    );

    if (!githubResponse.ok) {
      return jsonResponse(
        {
          error: "Failed to trigger repository_dispatch",
          status: githubResponse.status,
          body: await githubResponse.text(),
        },
        502,
      );
    }

    return jsonResponse(
      {
        ok: true,
        message: "repository_dispatch triggered",
      },
      202,
    );
  },
};

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body, null, 2), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
    },
  });
}
