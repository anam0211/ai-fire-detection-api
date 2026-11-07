// Backend-only client. Keep AI_API_KEY in server environment variables.
export class AiApiError extends Error {
  constructor(message, { status = 0, code = "HTTP_ERROR", detail = null } = {}) {
    super(message);
    this.name = "AiApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

export function createAiClient({ baseUrl, apiKey, timeoutMs = 120000 } = {}) {
  if (!baseUrl || typeof apiKey !== "string" || !apiKey.trim()) {
    throw new Error("Set AI_API_URL and AI_API_KEY on the web backend");
  }
  const parsed = new URL(baseUrl);
  if (!["http:", "https:"].includes(parsed.protocol) || parsed.username || parsed.password ||
      parsed.search || parsed.hash || parsed.pathname !== "/") {
    throw new Error("AI_API_URL must be an HTTP(S) origin without credentials, query or path");
  }
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new Error("Invalid timeoutMs");
  const base = parsed.origin;

  function checkDeviceId(deviceId) {
    if (typeof deviceId !== "string" || !/^[A-Za-z0-9_-]{1,64}$/.test(deviceId)) {
      throw new TypeError("device_id must contain 1..64 letters, digits, _ or -");
    }
  }

  async function request(path, { method = "GET", body, authenticated = true } = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(base + path, {
        method,
        redirect: "error", // Do not forward API credentials to an unexpected redirected host.
        headers: {
          Accept: "application/json",
          ...(authenticated ? { "X-API-Key": apiKey } : {}),
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
        signal: controller.signal,
      });
      let data;
      try {
        data = await response.json();
      } catch {
        throw new AiApiError("AI API returned an invalid JSON response", {
          status: response.status, code: "INVALID_JSON",
        });
      }
      if (!response.ok) {
        throw new AiApiError(`AI API returned HTTP ${response.status}`, {
          status: response.status, detail: data.detail,
        });
      }
      return data;
    } catch (error) {
      if (error instanceof AiApiError) throw error;
      throw new AiApiError(controller.signal.aborted ? "AI request timed out" : "AI API is unreachable", {
        code: controller.signal.aborted ? "TIMEOUT" : "NETWORK_ERROR",
      });
    } finally {
      clearTimeout(timer);
    }
  }

  return {
    async sendSample({ device_id, temperature, infrared }) {
      checkDeviceId(device_id);
      if (!Number.isFinite(temperature) || temperature < -40 || temperature > 125) {
        throw new TypeError("temperature must be a number from -40 to 125 C");
      }
      if (!Number.isInteger(infrared) || (infrared !== 0 && infrared !== 1)) {
        throw new TypeError("infrared must be the integer 0 or 1");
      }
      return request("/api/v1/sensor-data", {
        method: "POST", body: { device_id, temperature, infrared },
      });
    },
    async getStatus(deviceId) {
      checkDeviceId(deviceId);
      return request(`/api/v1/status/${encodeURIComponent(deviceId)}`);
    },
    getHealth() {
      return request("/health", { authenticated: false });
    },
  };
}
