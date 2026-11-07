// Live integration check. Run against a real API using a test-only device ID.
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { createAiClient } from "./ai-client.mjs";

const baseUrl = process.env.AI_API_URL;
const apiKey = process.env.AI_API_KEY;
const ai = createAiClient({ baseUrl, apiKey });
const id = `web_test_${randomUUID().replaceAll("-", "").slice(0, 12)}`;
const fixture = [29.18, 29.18, 29.23, 29.24, 29.2, 29.2, 29.18, 29.18, 29.13, 29.14];

assert.deepEqual(await ai.getHealth(), { ok: true, model: "IsolationForest", window_size: 10 });
await assert.rejects(ai.getStatus(id), (error) => error.status === 404);
await assert.rejects(
  createAiClient({ baseUrl, apiKey: "invalid-test-key" }).getStatus(id),
  (error) => error.status === 401,
);
let result;
for (let index = 0; index < fixture.length; index++) {
  result = await ai.sendSample({ device_id: id, temperature: fixture[index], infrared: 0 });
  assert.equal(result.status, index < 9 ? "COLLECTING" : "NORMAL");
  assert.equal(result.ai.ready, index === 9);
}
assert.deepEqual(await ai.getStatus(id), result);
const anomaly = await ai.sendSample({ device_id: id, temperature: 120, infrared: 0 });
assert.equal(anomaly.status, "ANOMALY");
assert.equal(anomaly.alarm_suggested, true);
const flame = await ai.sendSample({ device_id: id + "_ir", temperature: 29.2, infrared: 1 });
assert.equal(flame.status, "FLAME_SIGNAL");
assert.equal(flame.source, "DIRECT_SENSOR");
await assert.rejects(ai.sendSample({ device_id: id, temperature: "30", infrared: 0 }), TypeError);
await assert.rejects(ai.sendSample({ device_id: id, temperature: 30, infrared: true }), TypeError);
console.log("PASS web backend client: health, auth, 404, warmup, NORMAL, ANOMALY, IR, GET and validation");
console.log(`Test device: ${id}`);
