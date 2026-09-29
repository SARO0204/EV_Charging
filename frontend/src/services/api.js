import axios from "axios";

function normalizeResponseValue(value) {
  if (Array.isArray(value)) {
    return value.map(normalizeResponseValue);
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, nestedValue]) => [
        key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`),
        normalizeResponseValue(nestedValue),
      ]),
    );
  }
  return value;
}

function getDetailMessage(detail) {
  if (typeof detail === "string") {
    return detail;
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === "string") {
          return item;
        }

        const location = Array.isArray(item?.loc)
          ? item.loc
              .slice(
                ["body", "query", "path", "header", "cookie"].includes(
                  item.loc[0],
                )
                  ? 1
                  : 0,
              )
              .join(".")
          : "";
        const message =
          typeof item?.msg === "string"
            ? item.msg
            : typeof item?.message === "string"
              ? item.message
              : "";

        return message ? (location ? `${location}: ${message}` : message) : "";
      })
      .filter(Boolean);

    return messages.length ? `Validation error: ${messages.join("; ")}` : "";
  }

  if (detail && typeof detail === "object") {
    if (typeof detail.message === "string") {
      return detail.message;
    }
    if (typeof detail.msg === "string") {
      return detail.msg;
    }
  }

  return "";
}

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "",
  timeout: 20000,
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const detail = getDetailMessage(error?.response?.data?.detail);
    const status = error?.response?.status;
    error.message =
      detail ||
      (status === 503
        ? "Live data unavailable — Firebase is not configured."
        : status === 404
          ? "The requested GridFlow resource was not found."
          : "Unable to connect to GridFlow backend.");
    return Promise.reject(error);
  },
);

api.interceptors.response.use((response) => {
  response.data = normalizeResponseValue(response.data);
  return response;
});

export default api;
