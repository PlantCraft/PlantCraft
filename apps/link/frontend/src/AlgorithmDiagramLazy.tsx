/**
 * The algorithm's diagram for pages that only show it (a loop, a run): React Flow and the editor
 * come in their own chunk once the diagram is drawn, so these pages open without them.
 */
import { LoaderCircle } from "lucide-react";
import { lazy, Suspense, type ComponentProps } from "react";
import type { AlgorithmDiagram as Diagram } from "./AlgorithmEditor";
import { t } from "./i18n";

const LazyDiagram = lazy(() => import("./AlgorithmEditor").then((module) => ({ default: module.AlgorithmDiagram })));

export function AlgorithmDiagram(props: ComponentProps<typeof Diagram>) {
  const loading = <div className="alg-diagram alg-diagram-loading" style={{ height: props.height ?? 360 }}><LoaderCircle className="spin" /><span>{t("Drawing the algorithm…")}</span></div>;
  return <Suspense fallback={loading}><LazyDiagram {...props} /></Suspense>;
}
