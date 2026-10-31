// Baseline: what React alone weighs (every app already loads it), to subtract from the React cases.
import { createRoot } from "react-dom/client";
import { main, root } from "../harness.js";
main(async () => { createRoot(root()).render(<div>React</div>); return {}; });
