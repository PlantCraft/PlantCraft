import * as monaco from "monaco-editor/editor/editor.api";
import "monaco-editor/languages/definitions/python/register";
import { main, root, timed, frames } from "../harness.js";
import { pythonSource, TYPED } from "./common.js";
// No language workers: Python in Monaco has only the syntax colouring (no worker-based service).
self.MonacoEnvironment = { getWorker: () => new Worker(URL.createObjectURL(new Blob(["self.onmessage=()=>{}"], { type: "text/javascript" }))) };
main(async () => {
  const el = root();
  let editor;
  const open = await timed(() => { editor = monaco.editor.create(el, { value: pythonSource(), language: "python", automaticLayout: true, minimap: { enabled: true } }); });
  editor.setPosition({ lineNumber: 20, column: 1 });
  const t0 = performance.now();
  for (const ch of TYPED) { editor.trigger("bench", "type", { text: ch }); await frames(1); }
  const per_key_ms = +((performance.now() - t0) / TYPED.length - 1000 / 60).toFixed(2);
  const end = await timed(() => editor.revealLine(editor.getModel().getLineCount()));
  editor.revealLine(1);
  return { open, per_key_ms_over_frame: per_key_ms, jump_to_end: end };
});
