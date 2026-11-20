import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";

const source = await readFile(new URL("../hotel/api_wake.js", import.meta.url), "utf8");
const {default: wake} = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
const calls = [], timers = [], cleared = [];
let finish;
globalThis.fetch = (url, options) => {
  calls.push({url, options});
  return new Promise(resolve => { finish = resolve; });
};
globalThis.setTimeout = (callback, ms) => { timers.push({callback, ms}); return timers.length; };
globalThis.clearTimeout = id => cleared.push(id);

const parentElement = {dataset: {}};
const data = {url: "https://api.test/healthz", nonce: "public-nonce", timeoutMs: 90000};
wake({data: null, parentElement});
wake({data, parentElement});
wake({data, parentElement});
assert.equal(calls.length, 1);
assert.equal(calls[0].url, "https://api.test/healthz?_wavo_wake=public-nonce");
assert.equal(calls[0].options.method, "GET");
assert.equal(calls[0].options.credentials, "omit");
assert.equal(calls[0].options.keepalive, true);
assert.equal(calls[0].options.cache, "no-store");
assert.equal(calls[0].options.headers, undefined);
assert.equal(calls[0].options.body, undefined);
assert.equal(timers[0].ms, 90000);
timers[0].callback();
assert.equal(calls[0].options.signal.aborted, true);
finish({});
await new Promise(resolve => setImmediate(resolve));
assert.deepEqual(cleared, [1]);
assert.equal(calls.length, 1);
console.log("Browser wake: one credential-free request, rerun deduplication, bounded timeout; passed");
