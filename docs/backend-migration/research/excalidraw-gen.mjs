// Minimal Excalidraw scene generator + share-link exporter.
// Mirrors excalidraw-app/data/index.ts exportToBackend (verified against the
// bundle served by http://excalidraw.lan on 2026-09-09):
//   key   = AES-GCM-128 JWK "k"
//   data  = concat(metadata="null", json)  -> deflate -> AES-GCM
//   body  = concat(fileInfo, iv, ciphertext)   (4-byte version=1, then 4-byte BE length per chunk)
//   POST https://json.excalidraw.com/api/v2/post/  -> {id}
//   link  = http://excalidraw.lan/#json=<id>,<key>
import { webcrypto as crypto } from "node:crypto";
import { deflateSync, inflateSync } from "node:zlib";
import { writeFileSync } from "node:fs";

let seedCounter = 1;
const rnd = () => Math.floor(Math.random() * 2 ** 31);
const uid = (p = "el") => `${p}_${(seedCounter++).toString(36)}_${rnd().toString(36)}`;
const now = () => Date.now();

const FONT = 5; // Excalifont
const CHAR_W = 0.6; // approx glyph width factor for width estimation
const LINE_H = 1.25;

function textSize(text, fontSize) {
  const lines = text.split("\n");
  const longest = Math.max(...lines.map((l) => l.length));
  return {
    width: Math.ceil(longest * fontSize * CHAR_W),
    height: Math.ceil(lines.length * fontSize * LINE_H),
  };
}

function base(type, x, y, w, h, opts = {}) {
  return {
    id: opts.id || uid(type),
    type,
    x,
    y,
    width: w,
    height: h,
    angle: 0,
    strokeColor: opts.stroke || "#1e1e1e",
    backgroundColor: opts.bg || "transparent",
    fillStyle: opts.fillStyle || "solid",
    strokeWidth: opts.strokeWidth ?? 2,
    strokeStyle: opts.strokeStyle || "solid",
    roughness: opts.roughness ?? 1,
    opacity: opts.opacity ?? 100,
    groupIds: opts.groupIds || [],
    frameId: opts.frameId || null,
    roundness: opts.roundness === null ? null : { type: 3 },
    seed: rnd(),
    version: 1,
    versionNonce: rnd(),
    isDeleted: false,
    boundElements: [],
    updated: now(),
    link: opts.link || null,
    locked: false,
  };
}

export class Scene {
  constructor() {
    this.elements = [];
    this.byId = new Map();
  }

  add(el) {
    this.elements.push(el);
    this.byId.set(el.id, el);
    return el;
  }

  /** Free-floating text. */
  text(x, y, text, opts = {}) {
    const fontSize = opts.fontSize || 20;
    const { width, height } = textSize(text, fontSize);
    const el = {
      ...base("text", x, y, width, height, { ...opts, roundness: null }),
      text,
      fontSize,
      fontFamily: opts.fontFamily || FONT,
      textAlign: opts.align || "left",
      verticalAlign: "top",
      containerId: null,
      originalText: text,
      autoResize: true,
      lineHeight: LINE_H,
    };
    return this.add(el);
  }

  /** Rectangle (or ellipse/diamond) with a centered bound label. */
  box(x, y, w, h, label, opts = {}) {
    const shape = opts.shape || "rectangle";
    const container = this.add(base(shape, x, y, w, h, opts));
    if (label) {
      const fontSize = opts.fontSize || 16;
      const { width, height } = textSize(label, fontSize);
      const tw = Math.min(width, w - 16);
      const t = {
        ...base("text", x + (w - tw) / 2, y + (h - height) / 2, tw, height, {
          roundness: null,
          stroke: opts.textColor || opts.stroke || "#1e1e1e",
          frameId: opts.frameId || null,
          groupIds: opts.groupIds || [],
        }),
        text: label,
        fontSize,
        fontFamily: opts.fontFamily || FONT,
        textAlign: "center",
        verticalAlign: "middle",
        containerId: container.id,
        originalText: label,
        autoResize: true,
        lineHeight: LINE_H,
      };
      this.add(t);
      container.boundElements.push({ id: t.id, type: "text" });
    }
    return container;
  }

  /** Frame (named region). Elements added with frameId get clipped to it. */
  frame(x, y, w, h, name, opts = {}) {
    const el = {
      ...base("frame", x, y, w, h, { ...opts, roundness: null, strokeWidth: 2, roughness: 0 }),
      name,
    };
    el.strokeColor = opts.stroke || "#bbb";
    el.backgroundColor = "transparent";
    return this.add(el);
  }

  /**
   * Arrow between two boxes. Endpoints are computed on the box borders along
   * the center-to-center line unless `from`/`to` anchors are given
   * ("top"|"bottom"|"left"|"right" with optional fractional offset).
   */
  arrow(a, b, label, opts = {}) {
    const A = typeof a === "string" ? this.byId.get(a) : a;
    const B = typeof b === "string" ? this.byId.get(b) : b;
    const p1 = anchor(A, opts.from, B);
    const p2 = anchor(B, opts.to, A);
    const mids = opts.via || []; // optional intermediate absolute points
    const pts = [p1, ...mids, p2];
    const x0 = p1[0];
    const y0 = p1[1];
    const rel = pts.map(([x, y]) => [x - x0, y - y0]);
    const minX = Math.min(...rel.map((p) => p[0]));
    const minY = Math.min(...rel.map((p) => p[1]));
    const maxX = Math.max(...rel.map((p) => p[0]));
    const maxY = Math.max(...rel.map((p) => p[1]));
    const el = {
      ...base("arrow", x0, y0, maxX - minX, maxY - minY, {
        ...opts,
        roundness: opts.sharp ? null : { type: 2 },
      }),
      points: rel,
      lastCommittedPoint: null,
      startBinding: { elementId: A.id, focus: 0, gap: 4 },
      endBinding: { elementId: B.id, focus: 0, gap: 4 },
      startArrowhead: opts.startArrowhead ?? null,
      endArrowhead: opts.endArrowhead === undefined ? "arrow" : opts.endArrowhead,
      elbowed: false,
    };
    if (!opts.sharp) el.roundness = { type: 2 };
    this.add(el);
    A.boundElements.push({ id: el.id, type: "arrow" });
    B.boundElements.push({ id: el.id, type: "arrow" });
    if (label) {
      const fontSize = opts.fontSize || 13;
      const { width, height } = textSize(label, fontSize);
      // midpoint of the polyline (by segment count)
      const mi = Math.floor(pts.length / 2);
      const [mx, my] =
        pts.length % 2 === 0
          ? [(pts[mi - 1][0] + pts[mi][0]) / 2, (pts[mi - 1][1] + pts[mi][1]) / 2]
          : pts[mi];
      const lx = mx - width / 2 + (opts.labelDx || 0);
      const ly = my - height / 2 + (opts.labelDy || 0);
      const t = {
        ...base("text", lx, ly, width, height, {
          roundness: null,
          stroke: opts.labelColor || opts.stroke || "#1e1e1e",
          frameId: opts.frameId || null,
        }),
        text: label,
        fontSize,
        fontFamily: opts.fontFamily || FONT,
        textAlign: "center",
        verticalAlign: "middle",
        containerId: el.id,
        originalText: label,
        autoResize: true,
        lineHeight: LINE_H,
      };
      this.add(t);
      el.boundElements.push({ id: t.id, type: "text" });
    }
    return el;
  }

  toFile(appState = {}) {
    return {
      type: "excalidraw",
      version: 2,
      source: "http://excalidraw.lan",
      elements: this.elements,
      appState: { viewBackgroundColor: "#ffffff", gridSize: null, ...appState },
      files: {},
    };
  }
}

function center(el) {
  return [el.x + el.width / 2, el.y + el.height / 2];
}

function anchor(el, spec, other) {
  if (!spec) return borderPoint(el, center(other));
  const [side, fracRaw] = Array.isArray(spec) ? spec : [spec, 0.5];
  const frac = fracRaw ?? 0.5;
  switch (side) {
    case "top":
      return [el.x + el.width * frac, el.y];
    case "bottom":
      return [el.x + el.width * frac, el.y + el.height];
    case "left":
      return [el.x, el.y + el.height * frac];
    case "right":
      return [el.x + el.width, el.y + el.height * frac];
    default:
      return borderPoint(el, center(other));
  }
}

// Intersection of the ray from el's center towards `target` with el's border.
function borderPoint(el, target) {
  const [cx, cy] = center(el);
  const dx = target[0] - cx;
  const dy = target[1] - cy;
  if (dx === 0 && dy === 0) return [cx, cy];
  const hw = el.width / 2;
  const hh = el.height / 2;
  const tx = dx !== 0 ? hw / Math.abs(dx) : Infinity;
  const ty = dy !== 0 ? hh / Math.abs(dy) : Infinity;
  const t = Math.min(tx, ty);
  return [cx + dx * t, cy + dy * t];
}

// ---------------------------------------------------------------- export ---

const VERSION_BYTES = 4;
const CHUNK_LEN_BYTES = 4;
const CONCAT_VERSION = 1;

function concatBuffers(...buffers) {
  const total =
    VERSION_BYTES +
    CHUNK_LEN_BYTES * buffers.length +
    buffers.reduce((a, b) => a + b.byteLength, 0);
  const out = new Uint8Array(total);
  const dv = new DataView(out.buffer);
  let cursor = 0;
  dv.setUint32(cursor, CONCAT_VERSION);
  cursor += VERSION_BYTES;
  for (const b of buffers) {
    dv.setUint32(cursor, b.byteLength);
    cursor += CHUNK_LEN_BYTES;
    out.set(b, cursor);
    cursor += b.byteLength;
  }
  return out;
}

function splitBuffers(buf) {
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const version = dv.getUint32(0);
  if (version > CONCAT_VERSION) throw new Error(`invalid version ${version}`);
  const chunks = [];
  let cursor = VERSION_BYTES;
  while (cursor < buf.byteLength) {
    const len = dv.getUint32(cursor);
    cursor += CHUNK_LEN_BYTES;
    chunks.push(buf.slice(cursor, cursor + len));
    cursor += len;
  }
  return chunks;
}

async function importKey(k, usage) {
  return crypto.subtle.importKey(
    "jwk",
    { alg: "A128GCM", ext: true, k, key_ops: ["encrypt", "decrypt"], kty: "oct" },
    { name: "AES-GCM", length: 128 },
    false,
    [usage],
  );
}

export async function generateKey() {
  const key = await crypto.subtle.generateKey({ name: "AES-GCM", length: 128 }, true, [
    "encrypt",
    "decrypt",
  ]);
  return (await crypto.subtle.exportKey("jwk", key)).k;
}

export async function compress(jsonString, encryptionKey) {
  const fileInfo = new TextEncoder().encode(
    JSON.stringify({ version: 2, compression: "pako@1", encryption: "AES-GCM" }),
  );
  const metadata = new TextEncoder().encode(JSON.stringify(null));
  const data = new TextEncoder().encode(jsonString);
  const deflated = new Uint8Array(deflateSync(concatBuffers(metadata, data)));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const key = await importKey(encryptionKey, "encrypt");
  const encrypted = new Uint8Array(
    await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, deflated),
  );
  return concatBuffers(fileInfo, iv, encrypted);
}

export async function decompress(buf, decryptionKey) {
  const [infoBuf, iv, cipher] = splitBuffers(buf);
  const info = JSON.parse(new TextDecoder().decode(infoBuf));
  const key = await importKey(decryptionKey, "decrypt");
  const plain = new Uint8Array(
    await crypto.subtle.decrypt({ name: "AES-GCM", iv }, key, cipher),
  );
  const inflated = info.compression ? new Uint8Array(inflateSync(plain)) : plain;
  const [metadata, data] = splitBuffers(inflated);
  return {
    metadata: JSON.parse(new TextDecoder().decode(metadata)),
    data: new TextDecoder().decode(data),
  };
}

export async function exportToBackend(sceneFile, opts = {}) {
  const postUrl = opts.postUrl || "https://json.excalidraw.com/api/v2/post/";
  const origin = opts.origin || "http://excalidraw.lan/";
  const key = await generateKey();
  const payload = await compress(JSON.stringify(sceneFile), key);
  const res = await fetch(postUrl, { method: "POST", body: payload });
  const json = await res.json();
  if (!json.id) throw new Error(`export failed: ${JSON.stringify(json)}`);
  return { id: json.id, key, url: `${origin}#json=${json.id},${key}` };
}

export async function verifyLink(id, key, opts = {}) {
  const getUrl = opts.getUrl || "https://json.excalidraw.com/api/v2/";
  const res = await fetch(`${getUrl}${id}`);
  if (!res.ok) throw new Error(`fetch failed: ${res.status}`);
  const buf = new Uint8Array(await res.arrayBuffer());
  const { data } = await decompress(buf, key);
  return JSON.parse(data);
}

export function saveFile(path, sceneFile) {
  writeFileSync(path, JSON.stringify(sceneFile, null, 1));
}
