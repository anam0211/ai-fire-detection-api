import { createAiClient } from "./ai-client.mjs";

const ai = createAiClient({ baseUrl: process.env.AI_API_URL, apiKey: process.env.AI_API_KEY });

// Call this hook once for each NEW sensor sample already received by your web backend.
// Await sends sequentially per device. Do not call from page refresh/polling or replay stored data.
export async function onSensorSampleReceived(sensor) {
  try {
    const result = await ai.sendSample({
      device_id: sensor.device_id,
      temperature: sensor.temperature,
      infrared: sensor.infrared,
    });
    // Store result or emit it to your Dashboard using your existing service/socket code.
    return { available: true, result };
  } catch (error) {
    // Keep the original sensor data. Never replace an API error with NORMAL or score=0.
    return { available: false, error: { code: error.code ?? "CLIENT_ERROR", status: error.status ?? 0 } };
  }
}

// To read the latest AI result without adding another sensor sample:
// const result = await ai.getStatus("esp32_01");
