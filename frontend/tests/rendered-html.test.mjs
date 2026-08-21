import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the Thermoform application", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
  const html = await response.text();
  assert.match(html, /<title>Thermoform — Engineering Intelligence<\/title>/i);
  assert.match(html, /System overview/);
  assert.match(html, /Engineering workflow/);
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape/i);
});

test("React frontend uses the JavaScript FastAPI client", async () => {
  const [page, api, layout] = await Promise.all([
    readFile(new URL("../app/page.jsx", import.meta.url), "utf8"),
    readFile(new URL("../lib/api.js", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.jsx", import.meta.url), "utf8"),
  ]);
  assert.match(page, /api\s*\.\s*health\(\)/);
  assert.match(page, /api\s*\.\s*runPhase1/);
  assert.match(page, /api\s*\.\s*predict/);
  assert.match(page, /api\s*\.\s*predictModel/);
  assert.match(page, /api\s*\.\s*runPhase2/);
  assert.match(page, /api\s*\.\s*generateCad/);
  assert.match(api, /NEXT_PUBLIC_API_URL/);
  assert.match(api, /\/workflows\/phase1\/run/);
  assert.match(api, /\/models\/\$\{modelId\}\/predict/);
  assert.match(api, /\/workflows\/phase2\/run/);
  assert.match(api, /\/cad\/generate/);
  assert.match(api, /\/simulations\/predict/);
  assert.match(layout, /Thermoform — Engineering Intelligence/);
});
