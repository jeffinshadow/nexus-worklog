// Fotos na tarefa e na rotina (backend: routers/photos.py). A foto é reduzida
// aqui (lado maior 1600 px) e regravada em WebP — ou JPEG, onde o navegador não
// grava WebP —, o que apaga EXIF e GPS antes de sair do aparelho. A miniatura
// (320 px) vai junto. No celular o botão abre a câmera ou a galeria; no
// computador também dá para colar um print (Ctrl+V) ou arrastar o arquivo.
import { api } from "./api.js";
import { h, icon } from "./dom.js";
import { errorToast, modal, toast, undoLatest } from "./ui.js";

const MAX_SIDE = 1600, THUMB_SIDE = 320, MAX_BYTES = 1024 * 1024;

const isImage = (f) => f && /^image\//.test(f.type);

function canvasFor(bitmap, side) {
  const scale = Math.min(1, side / Math.max(bitmap.width, bitmap.height));
  const c = document.createElement("canvas");
  c.width = Math.max(1, Math.round(bitmap.width * scale));
  c.height = Math.max(1, Math.round(bitmap.height * scale));
  c.getContext("2d").drawImage(bitmap, 0, 0, c.width, c.height);
  return c;
}

const toBlob = (c, type, q) => new Promise((ok) => c.toBlob(ok, type, q));

// WebP onde dá; o Safari antigo devolve PNG: aí JPEG, bem menor.
async function encode(c, quality) {
  let b = await toBlob(c, "image/webp", quality);
  if (!b || b.type !== "image/webp") b = await toBlob(c, "image/jpeg", quality);
  return b;
}

const toB64 = (blob) => new Promise((ok, fail) => {
  const r = new FileReader();
  r.onload = () => ok(String(r.result).split(",")[1]);
  r.onerror = fail;
  r.readAsDataURL(blob);
});

export async function prepare(file) {
  let bitmap;
  try { bitmap = await createImageBitmap(file, { imageOrientation: "from-image" }); }
  catch { bitmap = await createImageBitmap(file); }
  const big = canvasFor(bitmap, MAX_SIDE);
  let image = null;
  for (const q of [0.82, 0.7, 0.55]) {  // cabe em 1 MB quase sempre na primeira
    image = await encode(big, q);
    if (image.size <= MAX_BYTES) break;
  }
  if (image.size > MAX_BYTES) throw new Error("A foto ficou grande demais mesmo reduzida.");
  const thumb = await encode(canvasFor(bitmap, THUMB_SIDE), 0.7);
  return { image: await toB64(image), thumb: await toB64(thumb), width: big.width, height: big.height };
}

// Envia uma ou mais fotos para `path` (/worklog/{id}/photos ou /recurring/{id}/photos?day=).
export async function upload(path, files) {
  const list = [...files].filter(isImage);
  let ok = 0;
  for (const f of list) {
    try { await api.post(path, await prepare(f)); ok++; }
    catch (e) { errorToast(e, "Não foi possível enviar a foto."); break; }
  }
  return ok;
}

export const thumbUrl = (id) => `/api/photos/${id}?thumb=true`;
export const photoUrl = (id) => `/api/photos/${id}`;

// Grade de miniaturas + "Adicionar foto". onChange: recarregar quem mostra.
export function photoGrid(photos, { path, onChange, label = "Fotos" }) {
  const input = h("input", { type: "file", accept: "image/*", multiple: "multiple", class: "hidden", "aria-label": "Escolher fotos" });
  const add = async (files) => {
    if (!files || ![...files].some(isImage)) return;
    toast("Enviando foto…");
    if (await upload(path, files)) { toast("Foto adicionada."); onChange(); }
  };
  input.addEventListener("change", () => { add(input.files); input.value = ""; });
  const grid = h("div", { class: "photo-grid" },
    ...photos.map((p, i) => h("button", { type: "button", class: "photo-thumb", "aria-label": `Abrir a foto ${i + 1} de ${photos.length}`,
      onClick: () => viewer(photos, i, onChange) },
    h("img", { src: thumbUrl(p.id), alt: "", loading: "lazy", width: "96", height: "96" }))),
    photos.length < 10 ? h("button", { type: "button", class: "photo-add", title: "Adicionar foto (câmera, galeria ou arquivo)",
      "aria-label": "Adicionar foto", onClick: () => input.click() }, icon("camera"), h("span", { text: "Foto" })) : null,
    input);
  // Arrastar o arquivo para cima da grade.
  grid.addEventListener("dragover", (ev) => { if ([...ev.dataTransfer.items].some((x) => x.kind === "file")) { ev.preventDefault(); grid.classList.add("drop"); } });
  grid.addEventListener("dragleave", () => grid.classList.remove("drop"));
  grid.addEventListener("drop", (ev) => { ev.preventDefault(); grid.classList.remove("drop"); add(ev.dataTransfer.files); });
  grid.dataset.label = label;
  grid.addFiles = add;
  return grid;
}

// Foto grande, com anterior/próxima (setas do teclado), baixar e excluir (com desfazer).
export function viewer(photos, start, onChange) {
  let i = start;
  const img = h("img", { class: "photo-big", alt: "" });
  const count = h("span", { class: "photo-count mono" });
  const prev = h("button", { type: "button", class: "icon", title: "Anterior", "aria-label": "Foto anterior", onClick: () => go(-1) }, icon("left"));
  const next = h("button", { type: "button", class: "icon", title: "Próxima", "aria-label": "Próxima foto", onClick: () => go(1) }, icon("right"));
  const dl = h("a", { class: "icon", title: "Baixar", "aria-label": "Baixar a foto", download: "" }, icon("download"));
  const del = h("button", { type: "button", class: "icon", title: "Excluir", "aria-label": "Excluir a foto", onClick: async () => {
    const p = photos[i];
    try {
      await api.del(`/photos/${p.id}`);
      dlg.close();
      onChange();
      toast("Foto excluída.", { action: "Desfazer", onAction: () => undoLatest("photo", p.id, onChange) });
    } catch (e) { errorToast(e); }
  } }, icon("trash"));
  function go(d) {
    i = (i + d + photos.length) % photos.length;
    img.src = photoUrl(photos[i].id);
    dl.href = photoUrl(photos[i].id);
    count.textContent = `${i + 1} de ${photos.length}`;
    prev.disabled = next.disabled = photos.length < 2;
  }
  const dlg = modal(h("div", { class: "photo-viewer" },
    h("div", { class: "photo-bar" }, count, h("span", { class: "spacer" }), prev, next, dl, del,
      h("button", { type: "button", class: "icon", title: "Fechar", "aria-label": "Fechar", onClick: () => dlg.close() }, icon("close"))),
    img));
  dlg.classList.add("photo-dialog");
  dlg.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowLeft") { ev.preventDefault(); go(-1); }
    if (ev.key === "ArrowRight") { ev.preventDefault(); go(1); }
  });
  go(0);
}

// Seção "Fotos" do detalhe da tarefa.
export function photosSection(t, onChange) {
  const sec = h("section", { class: "task-sec task-photos" },
    h("div", { class: "task-sec-head" }, icon("image"), h("h3", { text: "Fotos" }),
      t.photos.length ? h("span", { class: "count", text: String(t.photos.length) }) : null));
  const grid = photoGrid(t.photos, { path: `/worklog/${t.id}/photos`, onChange });
  sec.append(grid);
  if (matchMedia("(hover: hover)").matches && !t.photos.length)
    sec.append(h("p", { class: "dialog-note", text: "Dá para colar um print (Ctrl+V) ou arrastar a imagem para cá." }));
  sec.addFiles = grid.addFiles;
  return sec;
}

// Arquivos de imagem colados (Ctrl+V) — o detalhe da tarefa escuta enquanto aberto.
export const pastedImages = (ev) => [...(ev.clipboardData?.files || [])].filter(isImage);
