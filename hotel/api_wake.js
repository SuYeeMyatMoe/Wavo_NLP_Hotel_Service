// Render can return 502/no-deploy to another Render service without waking it.
// The coordinator grants one public browser request per shared readiness task.
// This is a wake hint only: the server still verifies health and authorization.
export default function ({data, parentElement}) {
  const host = parentElement.host || parentElement;
  if (!data?.url || !data?.nonce || host.dataset.wake === data.nonce) return;
  host.dataset.wake = data.nonce;
  const url = new URL(data.url);
  url.searchParams.set("_wavo_wake", data.nonce);
  const controller = new AbortController();
  const deadline = setTimeout(() => controller.abort(), Math.min(120000, data.timeoutMs));
  // Keep the request alive when the visitor navigates from the entrance to login.
  // No cookies, tokens, payloads, mutations, retries, or recurring pings.
  fetch(url.href, {
    method: "GET", credentials: "omit", cache: "no-store", keepalive: true,
    signal: controller.signal,
  }).catch(() => {}).finally(() => clearTimeout(deadline));
}
