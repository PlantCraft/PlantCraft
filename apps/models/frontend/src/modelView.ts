/**
 * One kind of model: every model is a block diagram. A model written as
 * Modelica code is the one block of its own diagram, its real inputs and outputs the block's
 * ports and its public parameters the block's settings; the code stays one click away.
 */
import type { BlockCatalog } from "@plantcraft/ui/blockEditor";
import type { BlockDiagram, ModelDetail } from "./types";

/** The catalog and the diagram a model's pages draw: its own, or the code's one block. */
export function modelView(found: ModelDetail, catalog: BlockCatalog): { catalog: BlockCatalog; diagram: BlockDiagram; code: boolean } {
  const block = found.code_block;
  if (!block) return { catalog, diagram: found.diagram, code: false };
  return {
    catalog: { ...catalog, blocks: [...catalog.blocks.filter((item) => item.block_id !== block.block_id), block] },
    diagram: { version: found.diagram.version ?? 1, nodes: [{ id: "model", block: block.block_id, label: found.name, parameters: {}, x: 0, y: 0 }], edges: [] },
    code: true,
  };
}

/** Saves in an editor window tell the model's page to read the model again. */
export const MODEL_CHANNEL = "modelcraft-models";

export function announceSaved(projectId: string, model: string): void {
  try {
    const channel = new BroadcastChannel(MODEL_CHANNEL);
    channel.postMessage({ projectId, model });
    channel.close();
  } catch { /* an older browser: the page reads it again when opened */ }
}

/** Calls back when an editor window saves this model. */
export function onSaved(projectId: string, model: string, callback: () => void): () => void {
  try {
    const channel = new BroadcastChannel(MODEL_CHANNEL);
    channel.onmessage = (event: MessageEvent<{ projectId: string; model: string }>) => {
      if (event.data?.projectId === projectId && event.data?.model === model) callback();
    };
    return () => channel.close();
  } catch { return () => undefined; }
}
