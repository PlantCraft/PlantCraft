import { X } from "lucide-react";
import { t } from "./i18n";
import { AssetSearch } from "./SourcePicker";
import type { AssetOption } from "./types";

/** Assets chosen one by one (search, then each shows as a chip). */
export function AssetChips({ label, value, assets, onChange, hint }: { label: string; value: string[]; assets: AssetOption[]; onChange: (value: string[]) => void; hint?: string }) {
  const name = (id: string) => { const found = assets.find((item) => item.id === id); return found ? (found.parent ? `${found.parent} › ${found.name}` : found.name) : id; };
  return <div><span className="al-label">{label}</span>
    {value.length > 0 && <div className="al-chips">{value.map((id) => <span key={id} className="al-chip">{name(id)}
      <button type="button" aria-label={t("Remove {name}", { name: name(id) })} onClick={() => onChange(value.filter((item) => item !== id))}><X size={12} /></button></span>)}</div>}
    <AssetSearch assets={assets.filter((item) => !value.includes(item.id))} value="" label={label} placeholder={t("Search assets to add")} onPick={(id) => { if (id && !value.includes(id)) onChange([...value, id]); }} />
    {hint && <small className="muted">{hint}</small>}
  </div>;
}

/** People (or anything named) chosen one by one from a list, each shown as a chip. */
export function NameChips({ label, value, options, onChange, hint }: { label: string; value: string[]; options: Array<{ id: string; label: string }>; onChange: (value: string[]) => void; hint?: string }) {
  const name = (id: string) => options.find((item) => item.id === id)?.label ?? id;
  const left = options.filter((item) => !value.includes(item.id));
  return <div><span className="al-label">{label}</span>
    {value.length > 0 && <div className="al-chips">{value.map((id) => <span key={id} className="al-chip">{name(id)}
      <button type="button" aria-label={t("Remove {name}", { name: name(id) })} onClick={() => onChange(value.filter((item) => item !== id))}><X size={12} /></button></span>)}</div>}
    <select aria-label={label} value="" disabled={!left.length} onChange={(event) => { if (event.target.value) onChange([...value, event.target.value]); }}>
      <option value="">{left.length ? t("Add…") : t("Nobody else to add")}</option>
      {left.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
    </select>
    {hint && <small className="muted">{hint}</small>}
  </div>;
}
