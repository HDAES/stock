import { useMemo, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import "./auth-login.css";

type StoredPassword = {
  salt: string;
  hash: string;
};

const PASSWORD_KEY = "stock_quant_password";
const AUTH_SESSION_KEY = "stock_quant_authenticated";
const PBKDF2_ITERATIONS = 150_000;

function bytesToBase64(bytes: ArrayBuffer | Uint8Array) {
  const value = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let binary = "";
  value.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return window.btoa(binary);
}

function base64ToBytes(value: string) {
  const binary = window.atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

async function derivePasswordHash(password: string, salt: Uint8Array) {
  const encoder = new TextEncoder();
  const keyMaterial = await window.crypto.subtle.importKey(
    "raw",
    encoder.encode(password),
    "PBKDF2",
    false,
    ["deriveBits"]
  );
  const derivedBits = await window.crypto.subtle.deriveBits(
    {
      name: "PBKDF2",
      hash: "SHA-256",
      salt,
      iterations: PBKDF2_ITERATIONS
    },
    keyMaterial,
    256
  );
  return bytesToBase64(derivedBits);
}

function getStoredPassword() {
  const raw = window.localStorage.getItem(PASSWORD_KEY);
  if (!raw) return null;

  try {
    return JSON.parse(raw) as StoredPassword;
  } catch {
    window.localStorage.removeItem(PASSWORD_KEY);
    return null;
  }
}

function isAuthenticated() {
  return window.sessionStorage.getItem(AUTH_SESSION_KEY) === "1";
}

async function setupPassword(password: string) {
  const salt = window.crypto.getRandomValues(new Uint8Array(16));
  const hash = await derivePasswordHash(password, salt);
  window.localStorage.setItem(PASSWORD_KEY, JSON.stringify({ salt: bytesToBase64(salt), hash }));
  window.sessionStorage.setItem(AUTH_SESSION_KEY, "1");
}

async function verifyPassword(password: string, stored: StoredPassword) {
  const hash = await derivePasswordHash(password, base64ToBytes(stored.salt));
  return hash === stored.hash;
}

async function bootstrapApp(root?: Root) {
  root?.unmount();
  await import("./main");
}

function LoginGate({ root }: { root: Root }) {
  const storedPassword = useMemo(() => getStoredPassword(), []);
  const firstSetup = !storedPassword;
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = password.trim();

    if (!value) {
      setError("请输入密码");
      return;
    }

    if (value.length < 4) {
      setError("密码至少需要 4 位");
      return;
    }

    setSubmitting(true);
    setError("");

    try {
      if (firstSetup) {
        await setupPassword(value);
        await bootstrapApp(root);
        return;
      }

      if (storedPassword && await verifyPassword(value, storedPassword)) {
        window.sessionStorage.setItem(AUTH_SESSION_KEY, "1");
        await bootstrapApp(root);
        return;
      }

      setError("密码错误，请重试");
    } catch {
      setError("浏览器加密能力不可用，请确认使用 HTTPS 或 localhost 访问");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <form className="auth-card" onSubmit={handleSubmit}>
        <div className="auth-logo">SQ</div>
        <h1>Stock Quant</h1>
        <p>{firstSetup ? "首次使用，请先设置访问密码" : "请输入密码进入系统"}</p>
        <label className="auth-field">
          <span>{firstSetup ? "设置密码" : "登录密码"}</span>
          <input
            autoFocus
            type="password"
            value={password}
            placeholder={firstSetup ? "请输入新密码" : "请输入密码"}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        {error && <div className="auth-error">{error}</div>}
        <button type="submit" disabled={submitting}>
          {submitting ? "处理中..." : firstSetup ? "设置并进入" : "登录"}
        </button>
      </form>
    </main>
  );
}

const container = document.getElementById("root");

if (!container) {
  throw new Error("Root element not found");
}

if (isAuthenticated()) {
  void bootstrapApp();
} else {
  const root = createRoot(container);
  root.render(<LoginGate root={root} />);
}
