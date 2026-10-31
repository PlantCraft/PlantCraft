/**
 * Analytics › Algorithms, the list: apart from the algorithm's page (AlgorithmsPage.tsx) so that
 * opening the list does not load the diagram editor (React Flow) and the test tools.
 */
import { chosenFolder, DataTable, FolderColumn, inFolder, MultiSelect, NO_FOLDER, rememberFolder, useAssistantPage, useFolders, type DataColumn } from "@plantcraft/ui";
import { Factory, Plus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { onSaved, tagOptions, withTags } from "./algorithms";
import { t } from "./i18n";
import { navigate } from "./nav";
import type { Algorithm, Me, ModelExample } from "./types";
import { ErrorBox, Heading, Link, Loading, Pill } from "./ui";

export const KIND_LABEL = { loop: "Control loops", signal: "Signals", asset: "Assets" } as const;

export function Tags({ tags }: { tags: string[] }) {
  return tags.length ? <span className="alg-tags">{tags.map((tag) => <span key={tag} className="tag">{tag}</span>)}</span> : <span className="muted">—</span>;
}

/** The Simulator demo plant's model algorithms on the built-in models, created with one button
 * (calibrated on the last hours) when the plant's loops are in PlantCraft. */
function ModelExamples({ onCreated }: { onCreated: () => void }) {
  const [items, setItems] = useState<ModelExample[]>([]);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  useEffect(() => { api.modelExamples().then(setItems).catch(() => setItems([])); }, []);
  const missing = items.filter((item) => !item.exists);
  if (!missing.length && !note) return null;
  async function create() {
    setBusy(true);
    try {
      const created = await api.createModelExamples();
      const waiting = created.filter((item) => !item.calibrated).map((item) => item.name);
      setNote(waiting.length
        ? t("Created {count}. Not calibrated yet: {names} (open it and press Calibrate on the Deviation block).", { count: created.length, names: waiting.join(", ") })
        : t("Created {count}, each calibrated on the last six hours.", { count: created.length }));
      setItems(await api.modelExamples());
      onCreated();
    } catch (err) { setNote(err instanceof Error ? err.message : String(err)); } finally { setBusy(false); }
  }
  return <div className="panel empty">
    {missing.length > 0 && <>
      <p>{t("The Simulator plant is here: Analytics can add its example model algorithms ({names}), each a built-in process model running beside the plant and judged with T².", { names: missing.map((item) => item.name).join(", ") })}</p>
      <div className="row-actions"><button className="button button-secondary" disabled={busy} onClick={() => void create()}><Factory size={16} />{busy ? t("Calibrating...") : t("Add the plant's model examples")}</button></div>
    </>}
    {note && <p className="muted small">{note}</p>}
  </div>;
}

export function AlgorithmsPage({ me }: { me: Me }) {
  const [items, setItems] = useState<Algorithm[] | null>(null);
  const [tags, setTags] = useState<string[]>([]);
  const [error, setError] = useState("");
  // Folders (round 9, D14): the left column picks one, kept in ?folder=.
  const [folders, reloadFolders] = useFolders("algorithm");
  const [folder, setFolder] = useState(() => chosenFolder(window.location.search));
  const load = () => api.algorithms().then((found) => { setItems(found); setError(""); }).catch((err: Error) => setError(err.message));
  useEffect(() => { void load(); return onSaved(() => void load()); }, []);
  useAssistantPage({ place: t("Analytics › Algorithms"), page: "linkcraft:algorithms", platformUrl: me.processcraft_url, facts: { algorithms: items?.length ?? 0 },
    view: { tags, rows: (items ?? []).slice(0, 30).map((item) => `${item.algorithm_id}: ${item.name.slice(0, 80)} (${item.subject_kind}, v${item.version})`) } });
  const options = useMemo(() => tagOptions(items ?? []), [items]);
  if (error) return <ErrorBox text={error} />;
  if (!items) return <Loading />;
  const columns: DataColumn<Algorithm>[] = [
    { key: "name", label: t("Algorithm"), sort: (item) => item.name.toLowerCase(), render: (item) => <><Link to={`/algorithms/${encodeURIComponent(item.algorithm_id)}`}><b>{item.name}</b></Link><small>{t(KIND_LABEL[item.subject_kind])}{item.group ? ` · ${t("group {name}", { name: item.group.name })}` : ""}</small></> },
    { key: "tags", label: t("Labels"), sort: (item) => (item.tags ?? []).join(", "), render: (item) => <Tags tags={item.tags ?? []} /> },
    { key: "author", label: t("Author"), sort: (item) => item.author, filter: true, render: (item) => item.author || "—" },
    { key: "owner", label: t("Owner"), className: "hide-narrow", sort: (item) => item.owner_name, filter: { value: (item) => item.owner_name || "—", label: t("Owner") }, render: (item) => item.owner_name || "—" },
    { key: "version", label: t("Version"), numeric: true, className: "hide-narrow", sort: (item) => item.version, render: (item) => item.version },
    { key: "used_by", label: t("Assets using it"), numeric: true, sort: (item) => item.used_by ?? 0, render: (item) => item.used_by ?? "—" },
    { key: "status", label: t("Status"), sort: (item) => (item.check.valid ? 1 : 0), filter: { options: [{ value: "ready", label: t("Ready") }, { value: "fix", label: t("Needs fixing") }], value: (item) => (item.check.valid ? "ready" : "fix"), label: t("Status") },
      render: (item) => <Pill status={item.check.valid ? "ok" : "bad"} label={item.check.valid ? t("Ready") : t("Needs fixing")} /> },
  ];
  return <>
    <Heading eyebrow={t("Algorithms and blocks")} title={t("Algorithms")}
      detail={t("An algorithm is a block diagram: it reads an asset's signals, checks their data, runs the methods and combines their results into a health, results on the asset, derived signals and messages. PlantCraft's own are read-only: duplicate one to make it yours.")}
      actions={me.can_edit && <Link to={folder && folder !== NO_FOLDER ? `/algorithms/new?folder=${encodeURIComponent(folder)}` : "/algorithms/new"} className="button button-primary"><Plus size={16} />{t("New algorithm")}</Link>} />
    <div className="pc-folder-layout">
    <FolderColumn kind="algorithm" list={folders} chosen={folder} onChoose={(value) => { setFolder(value); rememberFolder("/algorithms", value); }} total={items.length} canEdit={me.can_edit} onChanged={reloadFolders} />
    <section className="methods-main">
    <DataTable
      rows={withTags(items, tags).filter((item) => inFolder(folders, item.algorithm_id, folder))}
      columns={columns}
      rowKey={(item) => item.algorithm_id}
      onRowClick={(item) => navigate(`/algorithms/${encodeURIComponent(item.algorithm_id)}`)}
      searchText={(item) => `${item.name} ${item.description} ${(item.tags ?? []).join(" ")} ${item.author} ${item.owner_name} ${item.group?.name ?? ""}`}
      searchPlaceholder={t("Search name, label, author or owner")}
      initialSort={{ key: "name", descending: false }}
      toolbar={options.length > 0 && <MultiSelect label={t("Labels")} value={tags} onChange={setTags} options={options} />}
      label={t("Algorithms")}
      empty={folder ? t("No algorithm in this folder.") : t("No algorithm matches. Change the search or the filters.")}
    />
    </section>
    </div>
    {me.can_edit && !me.demo && <ModelExamples onCreated={() => void load()} />}
    <p className="muted section-lead">{t("When each algorithm runs, and on what, is on")} <Link to="/schedules">{t("Monitors")}</Link>.</p>
  </>;
}
