import { useRef, type ReactNode } from "react";
import { useDialogKeys } from "./dialogKeys";
import { X } from "lucide-react";
import { t } from "./i18n";

/**
 * The dialog every PlantCraft form opens in: a backdrop that closes it on a click outside, and
 * a header with the eyebrow, the title, a line under it and the close button. Escape closes it and
 * Tab stays inside, as in the ui's Dialog.
 */
export function Modal({ label, eyebrow, title, description, className, onClose, children }: {
  label: string;
  eyebrow: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  /** Classes added to `modal` (the form's own layout). */
  className?: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const box = useRef<HTMLDivElement>(null);
  useDialogKeys(box, onClose);
  return <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <div ref={box} className={className ? `modal ${className}` : "modal"} role="dialog" aria-modal="true" aria-label={label}>
      <header><div><span className="eyebrow">{eyebrow}</span><h2>{title}</h2>{description !== undefined && <p>{description}</p>}</div><button className="icon-button" type="button" onClick={onClose} aria-label={t("Close")}><X /></button></header>
      {children}
    </div>
  </div>;
}
