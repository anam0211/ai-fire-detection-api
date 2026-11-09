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
assert.equal(anomaly.status, "THERMAL_DANGER");
assert.equal(anomaly.risk_level, "HIGH");
assert.equal(anomaly.alarm_suggested, true);
const flame = await ai.sendSample({ device_id: id + "_ir", temperature: 29.2, infrared: 1 });
assert.equal(flame.status, "FLAME_SIGNAL");
assert.equal(flame.source, "DIRECT_SENSOR");
assert.equal(flame.risk_level, "LOW");
assert.equal(flame.alarm_suggested, false);
assert.equal(flame.assessment.policy_version, "near-heat-demo-v2");
const fusedId = id + "_fused";
for (let index = 0; index < 3; index++) {
  const fused = await ai.sendSample({ device_id: fusedId, temperature: 75, infrared: 1 });
  assert.equal(fused.risk_level, index === 2 ? "HIGH" : "MEDIUM");
  if (index < 2) await new Promise((resolve) => setTimeout(resolve, 1050));
}
await assert.rejects(ai.sendSample({ device_id: id, temperature: "30", infrared: 0 }), TypeError);
await assert.rejects(ai.sendSample({ device_id: id, temperature: 30, infrared: true }), TypeError);
console.log("PASS web backend client: auth, warmup, NORMAL, thermal HIGH, IR-only LOW, confirmed IR/heat HIGH, GET and validation");
console.log(`Test device: ${id}`);
