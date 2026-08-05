// frontend/src/api/client.js
import axios from "axios";
import { clearAuthState, getAuthToken } from "./auth";

function attachAuth(config) {
  const token = getAuthToken();
  config.headers = config.headers || {};

  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }

  return config;
}

function attach401Handler(apiInstance) {
  apiInstance.interceptors.response.use(
    (res) => res,
    (err) => {
      if (err.response?.status === 401) {
        clearAuthState();

        if (window.location.pathname !== "/login") {
          window.location.href = "/login";
        }
      }
      return Promise.reject(err);
    }
  );
}

const api = axios.create({
  baseURL: "/api",
  timeout: 10000,
});
api.interceptors.request.use(attachAuth);
attach401Handler(api);

export const apiLong = axios.create({
  baseURL: "/api",
  timeout: 10 * 60 * 1000,
});
apiLong.interceptors.request.use(attachAuth);
attach401Handler(apiLong);

export default api;
