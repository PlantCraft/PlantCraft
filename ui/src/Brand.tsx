import { APP_GLYPHS, appDisplayName, isFamilyApp, type AnyAppId } from "./appMarks.js";

/**
 * PlantCraft logo components. Colours for charts live in brandTheme.ts;
 * design tokens in tokens.css. See docs/brand.md.
 */
type MarkProps = {
  /** Rendered size in px (the mark is square). Reads down to 16. */
  size?: number;
  /** "tile": white glyph on a PlantCraft Blue tile (default). "glyph": the glyph alone in currentColor. */
  variant?: "tile" | "glyph";
  /** Accessible name; omit when the mark sits next to the written name. */
  title?: string;
  className?: string;
};

/**
 * The mark: a control valve (bowtie) on a process line, driven by an
 * instrument bubble, the ISA-5.1 way an engineer draws a control loop.
 */
export function BrandMark({ size = 32, variant = "tile", title, className }: MarkProps) {
  const tile = variant === "tile";
  const ink = tile ? "#ffffff" : "currentColor";
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 32 32"
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      focusable="false"
    >
      {tile && <rect width="32" height="32" rx="7" fill="var(--pc-app-processcraft, #0a66d0)" />}
      {APP_GLYPHS.processcraft.map(({ tag: Tag, attrs, fill }, index) => {
        const props = Object.fromEntries(Object.entries(attrs).map(([key, value]) => [key.replace(/-([a-z])/g, (_, c: string) => c.toUpperCase()), value]));
        return <Tag key={index} {...props} {...(fill ? { fill: ink } : { fill: "none", stroke: ink })} />;
      })}
    </svg>
  );
}

type LockupProps = {
  /** Mark size in px; the name scales with the surrounding CSS. */
  size?: number;
  /** Small line under the name, e.g. t("Platform") or "Dashboards". */
  subtitle?: string;
  className?: string;
};

/**
 * Mark + name, styled by the existing `.brand` rules (sidebar, sign-in,
 * dashboards top bar). "Plant" is set regular and "Craft" semibold.
 */
export function BrandLockup({ size = 36, subtitle, className }: LockupProps) {
  return (
    <span className={`brand${className ? ` ${className}` : ""}`}>
      <BrandMark size={size} className="pc-logo-mark" />
      <span>
        <strong className="pc-wordmark">
          <span>Plant</span>Craft
        </strong>
        {subtitle && <small>{subtitle}</small>}
      </span>
    </span>
  );
}

type AppMarkProps = {
  /** Family id (desk, processcraft, linkcraft, dashcraft, simcraft, alarmcraft, histcraft,
   * modelcraft), or the id of an app outside the family, drawn as a neutral letter tile. */
  app: AnyAppId;
  /** Outside the family: the app's name, whose first letter goes on the tile. */
  name?: string;
  /** Rendered size in px (square). Reads down to 16. */
  size?: number;
  /** "tile": white glyph on the app's tile colour (default). "glyph": the glyph alone in currentColor. */
  variant?: "tile" | "glyph";
  /** Accessible name; omit when the mark sits next to the written name. */
  title?: string;
  className?: string;
};

/**
 * The mark of one app of the family: same tile and stroke grammar as the
 * PlantCraft mark, its own glyph and tile colour (`--pc-app-<id>`).
 * Glyphs and colours live in appMarks.ts. See docs/brand.md, "App family".
 */
export function AppMark({ app, name, size = 32, variant = "tile", title, className }: AppMarkProps) {
  const tile = variant === "tile";
  const ink = tile ? "#ffffff" : "currentColor";
  if (!isFamilyApp(app)) {
    // An app outside the family: the same tile grid in a neutral colour (never a status hue),
    // with the first letter of its name (docs/brand.md, "App family").
    const letter = (name || app).trim().slice(0, 1).toUpperCase();
    return (
      <svg className={`pc-app-mark${className ? ` ${className}` : ""}`} width={size} height={size} viewBox="0 0 32 32"
        role={title ? "img" : undefined} aria-label={title} aria-hidden={title ? undefined : true} focusable="false" data-app={app}>
        {tile && <rect width="32" height="32" rx="7" fill="var(--pc-text-3)" />}
        <text x="16" y="21.5" textAnchor="middle" fontSize="16" fontWeight="600" fill={ink}>{letter}</text>
      </svg>
    );
  }
  return (
    <svg
      className={`pc-app-mark${className ? ` ${className}` : ""}`}
      width={size}
      height={size}
      viewBox="0 0 32 32"
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      focusable="false"
      data-app={app}
    >
      {tile && <rect width="32" height="32" rx="7" fill={`var(--pc-app-${app})`} />}
      {APP_GLYPHS[app].map(({ tag: Tag, attrs, fill }, index) => {
        const props = Object.fromEntries(Object.entries(attrs).map(([key, value]) => [key.replace(/-([a-z])/g, (_, c: string) => c.toUpperCase()), value]));
        return <Tag key={index} {...props} {...(fill ? { fill: ink } : { fill: "none", stroke: ink })} />;
      })}
    </svg>
  );
}

/**
 * App mark + name, styled by the same `.brand` rules as BrandLockup. A module shows its short name
 * ("Historian") over "PlantCraft"; the platform itself is the PlantCraft lockup. A module's
 * `subtitle` is not shown: the suite name takes that line.
 */
export function AppLockup({ app, name, size = 36, subtitle, className }: LockupProps & { app: AnyAppId; name?: string }) {
  if (app === "processcraft") return <BrandLockup size={size} subtitle={subtitle} className={className} />;
  return (
    <span className={`brand pc-app-lockup${className ? ` ${className}` : ""}`}>
      <AppMark app={app} name={name} size={size} className="pc-logo-mark" />
      <span>
        <strong className="pc-app-name">{appDisplayName(app, name)}</strong>
        <small className="pc-wordmark-small">
          <span>Plant</span>Craft
        </small>
      </span>
    </span>
  );
}
