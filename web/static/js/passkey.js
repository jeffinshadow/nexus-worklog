// Passkeys (WebAuthn): cadastrar neste aparelho e entrar sem senha. O servidor
// manda as opções em JSON (base64url); aqui viram o formato do navegador e a
// resposta volta em JSON. Usa as conversões nativas quando o navegador tem.
import { api } from "./api.js";

export const supported = () => !!window.PublicKeyCredential;

const toBuf = (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (s.length % 4)) % 4)), (c) => c.charCodeAt(0)).buffer;
const toB64u = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

function creationOptions(o) {
  if (PublicKeyCredential.parseCreationOptionsFromJSON) return PublicKeyCredential.parseCreationOptionsFromJSON(o);
  return { ...o, challenge: toBuf(o.challenge), user: { ...o.user, id: toBuf(o.user.id) },
    excludeCredentials: (o.excludeCredentials || []).map((c) => ({ ...c, id: toBuf(c.id) })) };
}

function requestOptions(o) {
  if (PublicKeyCredential.parseRequestOptionsFromJSON) return PublicKeyCredential.parseRequestOptionsFromJSON(o);
  return { ...o, challenge: toBuf(o.challenge), allowCredentials: (o.allowCredentials || []).map((c) => ({ ...c, id: toBuf(c.id) })) };
}

function credJSON(c) {
  if (typeof c.toJSON === "function") return c.toJSON();
  const r = c.response;
  const response = r.attestationObject
    ? { clientDataJSON: toB64u(r.clientDataJSON), attestationObject: toB64u(r.attestationObject), transports: r.getTransports ? r.getTransports() : [] }
    : { clientDataJSON: toB64u(r.clientDataJSON), authenticatorData: toB64u(r.authenticatorData), signature: toB64u(r.signature),
        userHandle: r.userHandle ? toB64u(r.userHandle) : null };
  return { id: c.id, rawId: toB64u(c.rawId), type: c.type, response };
}

// Cancelar na janela do aparelho não é erro para mostrar.
export const cancelled = (e) => e && (e.name === "NotAllowedError" || e.name === "AbortError");

export async function register(name) {
  const { challenge_id, options } = await api.post("/auth/passkeys/register/options");
  const cred = await navigator.credentials.create({ publicKey: creationOptions(options) });
  return api.post("/auth/passkeys/register", { challenge_id, credential: credJSON(cred), name });
}

// mediation "conditional": a passkey aparece nas sugestões do campo de e-mail
// (sem janela); o signal cancela quando a pessoa usa o botão ou a senha.
export async function login({ conditional = false, signal } = {}) {
  const { challenge_id, options } = await api.post("/auth/passkeys/login/options");
  const cred = await navigator.credentials.get({ publicKey: requestOptions(options), mediation: conditional ? "conditional" : "optional", signal });
  return api.post("/auth/passkeys/login", { challenge_id, credential: credJSON(cred) });
}

export async function conditionalAvailable() {
  try { return supported() && !!PublicKeyCredential.isConditionalMediationAvailable && (await PublicKeyCredential.isConditionalMediationAvailable()); }
  catch { return false; }
}
