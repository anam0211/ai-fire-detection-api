// ES module. The caller provides the URL and key at runtime.
// A key used in browser JavaScript is visible to that browser's user.
// For a public Dashboard, call through your backend and keep API_KEY on that backend.
export function createFireApi(baseUrl, apiKey) {
  const base = baseUrl.replace(/\/+$/, "");

  async function request(path, { method = "GET", body, timeoutMs = 120000 } = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(`${base}${path}`, {
        method,
        headers: {
          "X-API-Key": apiKey,
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
        signal: controller.signal,
      });
      const data = await response.json();
      if (!response.ok) {
        const error = new Error(`API returned HTTP ${response.status}`);
        error.status = response.status;
        error.detail = data.detail;
        throw error;
      }
      return data;
    } finally {
      clearTimeout(timer);
    }
  }

  return {
    sendSample(deviceId, temperature, infrared) {
      if (!Number.isFinite(temperature) || temperature < -40 || temperature > 125) {
        throw new TypeError("temperature must be a finite number from -40 to 125 C");
      }
      if (!Number.isInteger(infrared) || (infrared !== 0 && infrared !== 1)) {
        throw new TypeError("infrared must be the number 0 or 1");
      }
      return request("/api/v1/sensor-data", {
        method: "POST", body: { device_id: deviceId, temperature, infrared },
      });
    },
    getStatus(deviceId) {
      return request(`/api/v1/status/${encodeURIComponent(deviceId)}`);
    },
  };
}

// const api = createFireApi("https://YOUR-SERVICE.onrender.com", keyEnteredAtRuntime);
// const result = await api.getStatus("esp32_01");
// Show result.status, result.online, result.ai.ready and result.timestamp.
// Label ANOMALY as "Temperature/IR anomaly", without claiming a confirmed fire.
// Poll sequentially every 2 seconds; wait for each request before scheduling the next.
