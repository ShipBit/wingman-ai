// Wingman AI — current (Azure) architecture, derived from the repos on 2026-09-09.
import { Scene, saveFile, exportToBackend, verifyLink } from "./excalidraw-gen.mjs";

const s = new Scene();

// palette
const C = {
  user: { bg: "#e9ecef", stroke: "#495057" },
  client: { bg: "#d0ebff", stroke: "#1971c2" },
  azureFrame: "#0078d4",
  auth: { bg: "#ffe8cc", stroke: "#e8590c" },
  api: { bg: "#d3f9d8", stroke: "#2f9e44" },
  ai: { bg: "#e5dbff", stroke: "#7048e8" },
  legacy: { bg: "#f8f9fa", stroke: "#868e96" },
  ext: { bg: "#fff3bf", stroke: "#f08c00" },
  pay: { bg: "#ffd8a8", stroke: "#d9480f" },
  bad: "#c92a2a",
};

s.text(0, -120, "Wingman AI — Ist-Architektur (Stand 2026-09-09, aus Code abgeleitet)", { fontSize: 28 });
s.text(0, -80, "Rot = bekannte Schmerzpunkte", { fontSize: 16, stroke: C.bad });

// ---------------------------------------------------------------- frames ---
const fUser = s.frame(0, 0, 520, 620, "Rechner des Nutzers");
const fAzure = s.frame(640, 0, 1120, 1180, "Azure (Tenant shipbit.onmicrosoft.com)");
const fExt = s.frame(1880, 0, 560, 1180, "Drittanbieter");

// ---------------------------------------------------------- user machine ---
const client = s.box(40, 60, 440, 200,
  "Wingman Client\n(Tauri 2 + SvelteKit, statisch)\n\n@azure/msal-browser, Redirect http://localhost:5173\nLiest Plan aus ID-Token-Claims\nSubscribe-Seite, ToS-Dialog, Region-Auswahl",
  { ...C.client, frameId: fUser.id, fontSize: 14 });

const core = s.box(40, 340, 440, 220,
  "Wingman Core\n(Python-Sidecar, FastAPI + WebSocket)\n\nSecret »wingman_pro« = B2C-Access-Token\nWingmanSubscription-Provider:\n/ask, /transcribe-*, /generate-*-speech,\n/generate-image, /azure-voices, /inworld-voices",
  { ...C.client, frameId: fUser.id, fontSize: 14 });

s.arrow(client, core, "WebSocket: save_secret(token)\nclient_logged_in(plan)", { from: "bottom", to: "top", fontSize: 12, frameId: fUser.id });

// ------------------------------------------------------------------ azure ---
const b2c = s.box(680, 60, 500, 260,
  "Azure AD B2C\nCustom Policies (B2C_1A_SIGNUP_SIGNIN_SHIPBIT)\n\nIdPs: Google, GitHub, E-Mail/Passwort\n10 Extension-Attribute = Subscription-Kopie:\nWingmanSubscriptionPlan, PayProSubscriptionId,\nPayProSubscriptionEndDate, LastPayProSubscriptionPlan,\nPaddleUserId, StripeCancelDate, TermsConsentDateTime …",
  { ...C.auth, frameId: fAzure.id, fontSize: 13 });

s.text(690, 330, "SPA-Refresh-Token: 24 h, nicht verlängerbar\n→ täglicher Re-Login", { fontSize: 14, stroke: C.bad, frameId: fAzure.id });

const graph = s.box(1260, 100, 440, 120,
  "Microsoft Graph API\n(schreibt Extension-Attribute\nauf das B2C-User-Objekt)",
  { ...C.auth, frameId: fAzure.id, fontSize: 14 });

const webhook = s.box(1260, 280, 440, 130,
  "wingman-webhook\n(Azure Function, nicht in den 4 Repos)\nPayPro-IPN → Graph → B2C-Attribute",
  { ...C.api, frameId: fAzure.id, fontSize: 14, strokeStyle: "dashed" });

const slick = s.box(1260, 460, 440, 130,
  "slickgpt-api (Azure Function, C#/.NET 6)\nCheckTermsConsent / UpdateTermsConsent\n+ tote SlickGPT-Chat-Route",
  { ...C.legacy, frameId: fAzure.id, fontSize: 14 });

const api = s.box(680, 460, 500, 260,
  "wingman-api (Azure Functions, Python FastAPI)\n3 Deployments: europe / usa / asia\n\nprüft B2C-JWT + Plan-Claims (is_wingman_pro/ultra)\nnur »gpt-4.1-mini« erlaubt, Rest wird hart umgebogen\nkein Usage-Tracking, keine Limits pro Nutzer\nPayPro-Endpunkte: subscription / suspend / renew",
  { ...C.api, frameId: fAzure.id, fontSize: 13 });

const aoai = s.box(680, 800, 500, 150,
  "Azure OpenAI (Sweden Central / North Central US / Asia)\ngpt-4.1-mini · whisper · tts-hd · gpt-image-1-mini",
  { ...C.ai, frameId: fAzure.id, fontSize: 14 });

const speech = s.box(680, 990, 500, 130,
  "Azure AI Speech (3 Regionen)\nSTT mit Sprach-Autoerkennung · Neural-TTS-Stimmen\n(Nutzer-Configs referenzieren Stimmen per Name)",
  { ...C.ai, frameId: fAzure.id, fontSize: 14 });

const foundry = s.box(1260, 800, 440, 150,
  "Azure AI Foundry Serverless\nMistral Large (swedencentral)\nLlama 3 8B / 70B (eastus2)\n(aktuell durch Allowlist unerreichbar)",
  { ...C.legacy, frameId: fAzure.id, fontSize: 14 });

const insights = s.box(1260, 990, 440, 130,
  "Application Insights\n(nur Logs, keine Nutzer-Reports)",
  { ...C.legacy, frameId: fAzure.id, fontSize: 14 });

// -------------------------------------------------------------- external ---
const social = s.box(1920, 60, 480, 100,
  "Social IdPs\nGoogle · GitHub",
  { ...C.ext, frameId: fExt.id, fontSize: 14 });

const paypro = s.box(1920, 220, 480, 260,
  "PayPro Global (Merchant of Record)\n\nHosted Checkout mit billing-email +\nCustom-Feld x-azure-user-id (= B2C objectId)\nSubscription-API (GetDetails/Suspend/Renew)\nProducts-API (Preise/Währung)\nIPN-Webhooks → wingman-webhook",
  { ...C.pay, frameId: fExt.id, fontSize: 13 });

const inworld = s.box(1920, 540, 480, 100,
  "Inworld TTS API\n(Ultra-Tier, direkt aus wingman-api)",
  { ...C.ext, frameId: fExt.id, fontSize: 14 });

const legacyPay = s.box(1920, 700, 480, 110,
  "Legacy: Paddle-API (/subscription)\nStripe-Portal-Link im Client",
  { ...C.legacy, frameId: fExt.id, fontSize: 14, strokeStyle: "dashed" });

const website = s.box(1920, 870, 480, 130,
  "wingman-website (SvelteKit auf Vercel)\n/api/pricing → Client-Subscribe-Seite\nkein Login, kein Checkout-Bezug zum Account",
  { ...C.ext, frameId: fExt.id, fontSize: 14 });

const misc = s.box(1920, 1040, 480, 100,
  "Aptabase (Client-Analytics)\nrelease.wingman-ai.com = Cloudflare R2 (Updater)",
  { ...C.ext, frameId: fExt.id, fontSize: 14 });

// ------------------------------------------------------------------ edges ---
s.arrow(client, b2c, "Login (Auth-Code + PKCE)\nID-/Access-Token mit extension_*-Claims", { from: ["right", 0.3], to: ["left", 0.3], fontSize: 12, labelDy: -14 });
s.arrow(b2c, social, "OAuth", { from: ["top", 0.6], to: ["left", 0.5], via: [[930, 20], [1850, 20]], fontSize: 12 });
s.arrow(core, api, "Bearer-Token, region=…\nLLM / STT / TTS / Bild", { from: ["right", 0.5], to: ["left", 0.5], fontSize: 12, labelDy: -16 });
s.arrow(client, api, "Subscribe-Seite:\n/paypro-subscription, suspend, renew", { from: ["right", 0.8], to: ["left", 0.2], fontSize: 12, labelDy: 30 });
s.arrow(client, slick, "ToS: Check/UpdateTermsConsent", { from: ["bottom", 0.9], to: ["left", 0.8], via: [[440, 300], [600, 300], [600, 640], [1220, 640], [1220, 564]], fontSize: 12, labelDx: 100, labelDy: -10 });
s.arrow(api, b2c, "JWKS / Token-Validierung", { from: ["top", 0.3], to: ["bottom", 0.3], fontSize: 12 });
s.arrow(api, aoai, "", { from: ["bottom", 0.4], to: ["top", 0.4] });
s.arrow(api, speech, "", { from: ["bottom", 0.1], to: ["top", 0.1], via: [[730, 760], [660, 760], [660, 1050], [680, 1050]], sharp: true });
s.arrow(api, foundry, "", { from: ["bottom", 0.8], to: ["top", 0.5] });
s.arrow(api, inworld, "Inworld TTS (Ultra)", { from: ["right", 0.9], to: ["left", 0.5], via: [[1200, 720], [1200, 760], [1820, 760], [1820, 590]], fontSize: 12, labelDx: 0, labelDy: 0 });
s.arrow(api, paypro, "Subscription-API", { from: ["right", 0.2], to: ["left", 0.9], via: [[1220, 512], [1220, 440], [1840, 440], [1840, 454]], fontSize: 12, labelDx: 0, labelDy: -14 });
s.arrow(api, legacyPay, "Paddle-API (legacy)", { from: ["right", 0.6], to: ["left", 0.5], via: [[1210, 616], [1210, 700], [1780, 700], [1780, 755]], fontSize: 12, strokeStyle: "dashed" });
s.arrow(client, paypro, "Systembrowser: Checkout-URL\nx-azure-user-id + billing-email", { from: ["top", 0.5], to: ["top", 0.5], via: [[260, -40], [2160, -40]], fontSize: 12, labelDx: 700, labelDy: 0 });
s.arrow(paypro, webhook, "IPN (Subscription-Events)", { from: ["left", 0.5], to: ["right", 0.5], fontSize: 12 });
s.arrow(webhook, graph, "PATCH extension_*", { from: ["top", 0.5], to: ["bottom", 0.5], fontSize: 12 });
s.arrow(slick, graph, "PATCH TermsConsentDateTime", { from: ["top", 0.8], to: ["bottom", 0.8], via: [[1612, 440], [1740, 440], [1740, 160], [1700, 160]], fontSize: 12, sharp: true, labelDx: 60, labelDy: 0 });
s.arrow(graph, b2c, "", { from: ["left", 0.5], to: ["right", 0.5] });
s.arrow(client, website, "/api/pricing", { from: ["bottom", 0.1], to: ["left", 0.5], via: [[84, 290], [84, 600], [560, 600], [560, 1200], [1860, 1200], [1860, 935]], fontSize: 12, strokeStyle: "dashed", labelDx: 0, labelDy: 0 });
s.arrow(client, misc, "Events", { from: ["bottom", 0.2], to: ["left", 0.2], via: [[128, 300], [128, 580], [580, 580], [580, 1230], [1880, 1230], [1880, 1060]], fontSize: 12, strokeStyle: "dashed", endArrowhead: "arrow" });

const file = s.toFile();
saveFile("/tmp/wingman-arch/current.excalidraw", file);
console.log("elements:", s.elements.length);

if (process.argv.includes("--share")) {
  const { id, key, url } = await exportToBackend(file);
  const back = await verifyLink(id, key);
  console.log("share url:", url);
  console.log("roundtrip elements:", back.elements.length);
}
