/** Aaron, the setup guide's robot: an industrial arm with a sensor head (owner, 2026-11-03: "more
 * industrial", named Aaron). Small spots such as the corner launcher show the head only, since a
 * whole arm does not read at 44 px; the open card shows the whole arm, which moves with the mood.
 * Colours come from the suite tokens, so light and dark follow the theme (guideRobot.css). */
import { useId } from "react";
import "./guideRobot.css";

/** idle: on, waiting (amber light); talk, think, load, cheer: working (green light); sleep: off
 * (light out); error: down or in trouble (red light). */
export type GuideRobotMood = "idle" | "talk" | "cheer" | "sleep" | "think" | "load" | "error";

/** The head in its own 24 x 18 box: a sensor housing, a screen for a face, a status light on a
 * short mast. The face changes with the mood. */
function Head({ mood }: { mood: GuideRobotMood }) {
  const clip = `aaron-screen-${useId().replace(/:/g, "")}`;
  return <g className="aaron-head">
    <rect className="aaron-mast" x="11" y="-4" width="2" height="5" />
    <circle className="aaron-led" cx="12" cy="-4" r="2.2" />
    <rect className="aaron-shell" x="0" y="0" width="24" height="18" rx="6" />
    <clipPath id={clip}><rect x="3" y="3" width="18" height="12" rx="4" /></clipPath>
    <rect className="aaron-screen" x="3" y="3" width="18" height="12" rx="4" />
    <g clipPath={`url(#${clip})`}><Face mood={mood} /></g>
  </g>;
}

function Face({ mood }: { mood: GuideRobotMood }) {
  switch (mood) {
    case "cheer":
      return <path className="aaron-eye-line" d="M6.5 10.5l2-2 2 2M13.5 10.5l2-2 2 2" />;
    case "sleep":
      return <path className="aaron-eye-line" d="M6.5 9h4M13.5 9h4" />;
    case "error":
      return <path className="aaron-eye-line" d="M6.7 7.2l3.6 3.6M10.3 7.2l-3.6 3.6M13.7 7.2l3.6 3.6M17.3 7.2l-3.6 3.6" />;
    case "load":
      /* A bar that keeps running right: it leaves the screen on one side and comes back on the other. */
      return <rect className="aaron-eye aaron-scan" x="-4" y="7.7" width="7" height="2.6" rx="1.3" />;
    case "think":
      return <g className="aaron-ask">
        <path className="aaron-eye-line" d="M6.9 7.4a1.7 1.7 0 1 1 2.3 1.6c-.5.2-.7.5-.7 1.1" />
        <path className="aaron-eye-line" d="M13.9 7.4a1.7 1.7 0 1 1 2.3 1.6c-.5.2-.7.5-.7 1.1" />
        <circle className="aaron-eye" cx="8.5" cy="12.3" r="0.9" />
        <circle className="aaron-eye" cx="15.5" cy="12.3" r="0.9" />
      </g>;
    case "talk":
      return <>
        <g className="aaron-eye aaron-blink"><ellipse cx="8.5" cy="8" rx="2.2" ry="2.6" /><ellipse cx="15.5" cy="8" rx="2.2" ry="2.6" /></g>
        <rect className="aaron-eye aaron-mouth" x="9.5" y="11.6" width="5" height="1.6" rx="0.8" />
      </>;
    default:
      return <g className="aaron-glance"><g className="aaron-eye aaron-blink"><ellipse cx="8.5" cy="9" rx="2.2" ry="2.8" /><ellipse cx="15.5" cy="9" rx="2.2" ry="2.8" /></g></g>;
  }
}

/** ``view="head"`` for small spots (launcher, avatars), ``view="full"`` for the whole arm. */
export function GuideRobot({ mood = "idle", size = 48, view = "full" }: { mood?: GuideRobotMood; size?: number; view?: "head" | "full" }) {
  if (view === "head") {
    return <svg className={`aaron aaron-head-only aaron-${mood}`} width={size} height={size} viewBox="-2 -7 28 28" aria-hidden="true">
      <Head mood={mood} />
    </svg>;
  }
  return <svg className={`aaron aaron-full aaron-${mood}`} width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
    <rect className="aaron-base" x="12" y="57" width="30" height="5" rx="2" />
    <rect className="aaron-turret" x="18" y="49" width="18" height="9" rx="3" />
    <line className="aaron-link aaron-link-low" x1="27" y1="50" x2="20" y2="28" />
    <circle className="aaron-joint" cx="27" cy="50" r="4.5" />
    <g className="aaron-arm">
      <line className="aaron-link aaron-link-up" x1="20" y1="28" x2="40" y2="18" />
      <g transform="translate(36 7)"><Head mood={mood} /></g>
    </g>
    <circle className="aaron-joint" cx="20" cy="28" r="5" />
    <circle className="aaron-pin" cx="20" cy="28" r="1.8" />
  </svg>;
}
