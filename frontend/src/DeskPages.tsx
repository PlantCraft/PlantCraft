/**
 * Desk's shared page heading. Team moved to TeamPage.tsx in round 7; what
 * came to the person is in Messages' Notifications since 2026-10-24 (Notifications.tsx).
 */
import { Heading } from "@plantcraft/ui";
import type { ReactNode } from "react";
import "./desk.css";

/** A page's title block, as every PlantCraft page draws it. */
export function PageHeading({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: ReactNode }) {
  return <Heading eyebrow={eyebrow} title={title} detail={description} actions={action} />;
}
