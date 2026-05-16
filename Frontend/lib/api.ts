import axios from "axios";

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000",
});

api.interceptors.request.use((config) => {
  if (config.data instanceof FormData) {
    delete config.headers["Content-Type"];
  } else if (
    config.data !== undefined &&
    config.headers["Content-Type"] === undefined
  ) {
    config.headers["Content-Type"] = "application/json";
  }
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("confam_access_token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  return config;
});

function rawDetail(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) =>
          typeof item === "object" && item !== null && "msg" in item
            ? String((item as { msg: string }).msg)
            : JSON.stringify(item),
        )
        .join(", ");
    }
    return error.response?.statusText || error.message || "";
  }
  if (error instanceof Error) return error.message;
  return "";
}

/** Maps API / transport failures to short, consumer-safe copy (no raw stack traces). */
export function extractApiError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const status = error.response?.status;
    const raw = rawDetail(error).trim();
    const lower = raw.toLowerCase();

    if (status === 429 || lower.includes("too many requests")) {
      return "Confam is a bit busy right now. Try again in a moment.";
    }
    if (status === 401) {
      return "Please sign in again to continue.";
    }
    if (status === 413) {
      return "That file is too large. Try a smaller photo or shorter voice note.";
    }
    if (status === 503) {
      return "Confam is temporarily unavailable. Try again shortly.";
    }
    if (status === 502 || status === 504) {
      return "Network issue. Please try again.";
    }
    if (
      lower.includes("openrouter") ||
      lower.includes("timeout") ||
      lower.includes("econnreset") ||
      lower.includes("network error")
    ) {
      return "Network issue. Please try again.";
    }
    if (lower.includes("fetch") && lower.includes("failed")) {
      return "Network issue. Please try again.";
    }
    if (
      raw &&
      raw.length <= 160 &&
      !/(traceback|exception|psycopg|sqlalchemy|openrouter|undefined column)/i.test(raw)
    ) {
      return raw;
    }
    if (raw && status && status >= 500) {
      return "Something went wrong on our side. Please try again.";
    }
    return (
      error.response?.statusText ||
      error.message ||
      "Something went wrong. Try again."
    );
  }
  if (error instanceof Error) {
    const m = error.message;
    if (/timeout|network|fetch/i.test(m)) return "Network issue. Please try again.";
    return m.length <= 160 ? m : "Something went wrong. Try again.";
  }
  return "Something went wrong. Try again.";
}

export default api;
