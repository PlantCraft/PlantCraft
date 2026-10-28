/** The part of the plant a person or a group's members see (docs/asset-scope.md): the whole plant,
 * or only some roots of the asset tree and everything under them. */
import { useEffect, useMemo, useState } from "react";
import { requestJson } from "./api";
import { t } from "./i18n";

type TreeItem = { asset_id: string; name: string; kind_label?: string; kind: string; parent_id: string | null };
// The levels offered without a search: the installation, its units and what each unit holds.
const SHOWN_DEPTH = 3;

export function AssetScopeField({ value, onChange, legend, hint, disabled }: { value: string[] | null; onChange: (value: string[] | null) => void; legend: string; hint: string; disabled?: boolean }) {
  const limited = value !== null;
  const [items, setItems] = useState<TreeItem[] | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    if (!limited || items !== null) return;
    requestJson<{ items: TreeItem[] }>("/api/assets").then((tree) => setItems(tree.items)).catch(() => setError(t("Could not load the assets.")));
  }, [limited, items]);
  const rows = useMemo(() => {
    if (!items) return [];
    const children = new Map<string | null, TreeItem[]>();
    const known = new Set(items.map((item) => item.asset_id));
    for (const item of items) {
      const parent = item.parent_id && known.has(item.parent_id) ? item.parent_id : null;
      children.set(parent, [...(children.get(parent) ?? []), item]);
    }
    const found: Array<{ item: TreeItem; depth: number }> = [];
    const needle = query.trim().toLowerCase();
    const walk = (parent: string | null, depth: number) => {
      for (const item of children.get(parent) ?? []) {
        const match = !needle || `${item.asset_id} ${item.name}`.toLowerCase().includes(needle);
        if (match && (needle || depth < SHOWN_DEPTH)) found.push({ item, depth: needle ? 0 : depth });
        if (needle || depth + 1 < SHOWN_DEPTH) walk(item.asset_id, depth + 1);
      }
    };
    walk(null, 0);
    return found.slice(0, 300);
  }, [items, query]);
  const chosen = value ?? [];
  const names = new Map((items ?? []).map((item) => [item.asset_id, item.name]));
  function toggle(id: string) {
    onChange(chosen.includes(id) ? chosen.filter((item) => item !== id) : [...chosen, id]);
  }
  return <fieldset className="field-span ac-fieldset" disabled={disabled}>
    <legend>{legend}</legend>
    <p className="ac-hint">{hint}</p>
    <div className="ac-scope-mode" role="radiogroup">
      <label className="ac-check"><input type="radio" name={`scope-${legend}`} checked={!limited} onChange={() => onChange(null)} /> {t("The whole plant")}</label>
      <label className="ac-check"><input type="radio" name={`scope-${legend}`} checked={limited} onChange={() => onChange(chosen)} /> {t("Only these assets and what is under them")}</label>
    </div>
    {limited && <div className="ac-scope">
      {chosen.length > 0 && <p className="ac-scope-chosen">{chosen.map((id) => <button type="button" key={id} className="ac-scope-chip" title={t("Remove")} onClick={() => toggle(id)}>{names.get(id) ?? id} ×</button>)}</p>}
      {chosen.length === 0 && <p className="ac-hint">{t("No asset chosen: nothing of the plant is visible.")}</p>}
      {error && <p className="form-error">{error}</p>}
      <input type="search" value={query} placeholder={t("Search assets")} aria-label={t("Search assets")} onChange={(event) => setQuery(event.target.value)} />
      <div className="ac-scope-tree">{rows.map(({ item, depth }) => <label key={item.asset_id} className="ac-check" style={{ paddingLeft: depth * 16 }}>
        <input type="checkbox" checked={chosen.includes(item.asset_id)} onChange={() => toggle(item.asset_id)} /> {item.name} <small className="muted">{item.kind_label ?? item.kind}</small>
      </label>)}</div>
    </div>}
  </fieldset>;
}
