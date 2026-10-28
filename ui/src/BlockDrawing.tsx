/**
 * A block as the diagram draws it (round 9 M1, M2), for its page's Overview in Link and Models:
 * the box with its picture (or its name), the inputs on the left and the outputs on the right,
 * each with its name and unit. And the field that chooses the picture: a PNG, JPEG, WebP or SVG
 * of at most 256 KB, read in the browser and checked again by the server
 * (`plantcraft_sdk.images`), which rebuilds an SVG without anything that runs.
 */
import { ImagePlus, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import type { BlockSpec, PortSpec } from "./blockModel.js";
import { t } from "./i18n.js";

export const IMAGE_MAX_BYTES = 256 * 1024;
export const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp", "image/svg+xml"];

/** Why a chosen file cannot be a block's picture ("" when it can). */
export function imageProblem(file: Pick<File, "type" | "size">): string {
  if (!IMAGE_TYPES.includes(file.type)) return t("A block's image is a PNG, JPEG, WebP or SVG file.");
  if (file.size > IMAGE_MAX_BYTES) return t("The image is {size} KB: a block's image is at most 256 KB.", { size: Math.ceil(file.size / 1024) });
  return "";
}

/** The image paths of a catalog's blocks as the browser reaches them (the app's `href`). */
export function withImageHrefs<T extends { image?: string | null }>(blocks: T[], href: (path: string) => string): T[] {
  return blocks.map((block) => (block.image && block.image.startsWith("/") ? { ...block, image: href(block.image) } : block));
}

function Port({ port, side }: { port: PortSpec; side: "in" | "out" }) {
  return <li className={`pc-bd-port pc-bd-${side}`} title={port.description}>
    <i aria-hidden="true" />
    <span>{port.label || port.port}{port.multiple ? " …" : ""}</span>
    {port.unit && <small>{port.unit}</small>}
  </li>;
}

/** The block drawn as in the diagram, with its ports named. */
export function BlockDrawing({ spec, caption }: { spec: Pick<BlockSpec, "name" | "inputs" | "outputs"> & { image?: string | null }; caption?: string }) {
  return <figure className="pc-block-drawing" aria-label={t("Drawing of {name}", { name: spec.name })}>
    <ul className="pc-bd-side pc-bd-inputs" aria-label={t("Inputs")}>
      {spec.inputs.map((port) => <Port key={port.port} port={port} side="in" />)}
    </ul>
    <div className="pc-bd-box">
      <strong>{spec.name}</strong>
      {spec.image ? <img src={spec.image} alt="" draggable={false} /> : <span className="pc-bd-empty" aria-hidden="true" />}
    </div>
    <ul className="pc-bd-side pc-bd-outputs" aria-label={t("Outputs")}>
      {spec.outputs.map((port) => <Port key={port.port} port={port} side="out" />)}
    </ul>
    {caption && <figcaption>{caption}</figcaption>}
  </figure>;
}

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error(t("The file cannot be read.")));
    reader.readAsDataURL(file);
  });
}

/** Choose, change or take out a block's picture. `value` is a data URL or a URL ("" for none). */
export function BlockImageField({ value, onChange, disabled, id = "pc-block-image" }: { value: string; onChange: (image: string) => void; disabled?: boolean; id?: string }) {
  const input = useRef<HTMLInputElement | null>(null);
  const [problem, setProblem] = useState("");
  async function choose(file: File | undefined) {
    if (!file) return;
    const found = imageProblem(file);
    setProblem(found);
    if (found) return;
    try { onChange(await readAsDataUrl(file)); } catch (err) { setProblem(err instanceof Error ? err.message : String(err)); }
  }
  return <div className="pc-block-image-field">
    <div className="pc-bif-preview">{value ? <img src={value} alt={t("The block's image")} /> : <span className="muted small">{t("No image: the block shows its name.")}</span>}</div>
    <div className="pc-bif-actions">
      <input ref={input} id={id} type="file" accept={IMAGE_TYPES.join(",")} hidden disabled={disabled}
        onChange={(event) => { void choose(event.target.files?.[0]); event.target.value = ""; }} />
      <button type="button" className="button button-secondary" disabled={disabled} onClick={() => input.current?.click()}><ImagePlus size={16} />{value ? t("Change the image") : t("Choose an image")}</button>
      {value && <button type="button" className="button button-secondary" disabled={disabled} onClick={() => { setProblem(""); onChange(""); }}><Trash2 size={16} />{t("Take the image out")}</button>}
      <small className="muted">{t("PNG, JPEG, WebP or SVG, at most 256 KB. It shows in the diagram, the palette and the block's page.")}</small>
    </div>
    {problem && <p className="pc-bif-problem" role="alert">{problem}</p>}
  </div>;
}
