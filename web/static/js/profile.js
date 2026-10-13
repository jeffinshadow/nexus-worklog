// Quem é a pessoa na interface: a foto (ou as iniciais) e o preparo da foto
// antes do envio — recorte quadrado e redução no próprio navegador, o que
// também descarta os metadados (inclusive a localização) da foto original.
import { h } from "./dom.js";

export function avatar(p, size = "sm") {
  const cls = `avatar avatar-${size}`;
  if (p && p.avatar) return h("img", { class: cls, src: p.avatar, alt: "" });
  const name = (p && p.name) || "?";
  const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
  let hash = 0;
  for (const c of name) hash = (hash * 31 + c.charCodeAt(0)) >>> 0;
  const el = h("span", { class: cls, "aria-hidden": "true", text: initials });
  el.style.setProperty("--av-h", String(hash % 360)); // a mesma pessoa, sempre a mesma cor
  return el;
}

const MAX_BYTES = 250 * 1024;

export async function squarePhoto(file, size = 256) {
  const bmp = await createImageBitmap(file);
  const side = Math.min(bmp.width, bmp.height);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  canvas.getContext("2d").drawImage(bmp, (bmp.width - side) / 2, (bmp.height - side) / 2, side, side, 0, 0, size, size);
  if (bmp.close) bmp.close();
  for (const [type, q] of [["image/webp", 0.86], ["image/jpeg", 0.86], ["image/jpeg", 0.7]]) {
    const blob = await new Promise((res) => canvas.toBlob(res, type, q));
    if (blob && blob.type === type && blob.size <= MAX_BYTES) return blob;
  }
  throw new Error("Não foi possível reduzir a foto.");
}
