/**
 * New library (owner, round 10, 2026-10-26): blocks sit in libraries, not folders. A library
 * made on this site has a name and a line on what goes in it; the Blocks page lists it after
 * Link's and New block puts blocks in it.
 */
import { Dialog } from "@plantcraft/ui";
import { FolderPlus } from "lucide-react";
import { useState } from "react";
import { api } from "./api";
import { forgetBlockCatalog } from "./AlgorithmEditor";
import { t } from "./i18n";

export function NewLibraryDialog({ onClose, onMade }: { onClose: () => void; onMade: (library: { library: string; name: string }) => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function make() {
    setBusy(true); setError("");
    try {
      const made = await api.createLibrary(name.trim(), description.trim());
      forgetBlockCatalog();
      onMade(made);
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); setBusy(false); }
  }
  return <Dialog title={t("New library")} onClose={onClose} initialFocus="#blk-library-name" onSubmit={(event) => { event.preventDefault(); if (name.trim()) void make(); }}
    footer={<><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><button type="submit" className="button button-primary" disabled={busy || !name.trim()}>{t("Make the library")}</button></>}>
    <label className="pc-field">{t("Name")}<input id="blk-library-name" value={name} maxLength={80} onChange={(event) => setName(event.target.value)} placeholder={t("Heat exchangers")} /></label>
    <label className="pc-field">{t("What goes in it (optional)")}<input id="blk-library-description" value={description} maxLength={300} onChange={(event) => setDescription(event.target.value)} /></label>
    {error && <p className="notice notice-error" role="alert">{error}</p>}
  </Dialog>;
}

/** The button that opens it, under the libraries and beside a block's Library. */
export function NewLibraryButton({ className, onMade }: { className?: string; onMade: (library: { library: string; name: string }) => void }) {
  const [open, setOpen] = useState(false);
  return <>
    <button type="button" className={className ?? "pc-folder-new"} onClick={() => setOpen(true)}><FolderPlus size={15} />{t("New library")}</button>
    {open && <NewLibraryDialog onClose={() => setOpen(false)} onMade={(made) => { setOpen(false); onMade(made); }} />}
  </>;
}
