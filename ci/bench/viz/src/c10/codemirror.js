import { EditorView, basicSetup } from "codemirror";
import { python } from "@codemirror/lang-python";
import { main, root, timed, frames } from "../harness.js";
import { pythonSource, TYPED } from "./common.js";
main(async () => {
  const el = root();
  let view;
  const open = await timed(() => { view = new EditorView({ doc: pythonSource(), extensions: [basicSetup, python(), EditorView.theme({ "&": { height: "100%" }, ".cm-scroller": { overflow: "auto" } })], parent: el }); });
  view.dispatch({ selection: { anchor: 400 } });
  const t0 = performance.now();
  for (const ch of TYPED) { view.dispatch(view.state.replaceSelection(ch)); await frames(1); }
  const per_key_ms = +((performance.now() - t0) / TYPED.length - 1000 / 60).toFixed(2);
  const end = await timed(() => view.dispatch({ selection: { anchor: view.state.doc.length }, scrollIntoView: true }));
  view.dispatch({ selection: { anchor: 0 }, scrollIntoView: true });
  return { open, per_key_ms_over_frame: per_key_ms, jump_to_end: end };
});
