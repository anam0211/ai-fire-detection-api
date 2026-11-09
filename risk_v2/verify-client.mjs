// Exercise the existing backend client against the experimental v2 contract.
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { createAiClient } from "../web_client/ai-client.mjs";

const client = createAiClient({baseUrl: process.env.AI_API_URL, apiKey: process.env.AI_API_KEY});
const id = `v2_web_${randomUUID().slice(0, 8)}`;
assert.equal((await client.getHealth()).ok, true);
const hot = await client.sendSample({device_id: id, temperature: 100, infrared: 0});
assert.equal(hot.status, "THERMAL_DANGER");
assert.equal(hot.risk_level, "HIGH");
assert.equal(hot.alarm_suggested, true);
assert.equal(hot.assessment.experimental, true);
assert.equal(hot.ai.ready, false);
assert.deepEqual(await client.getStatus(id), hot);
const ir = await client.sendSample({device_id: id + "_ir", temperature: 29.2, infrared: 1});
assert.equal(ir.risk_level, "LOW");
assert.equal(ir.alarm_suggested, false);
console.log("PASS existing Node backend client with v2: thermal HIGH without IR, IR-only LOW near stove, assessment and GET");
