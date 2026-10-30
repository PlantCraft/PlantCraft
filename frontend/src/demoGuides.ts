/**
 * The demo's guides by role: a visitor says what they do, and a guide walks
 * them through the few screens that matter most to that role, across the apps, in its words. The
 * stops point at the demo story (`processcraft demo seed`): a fixed page ("/alarm/alarms"), or an
 * object by its name ("Plant overview"), whose page on this installation the seed wrote
 * (`GET /api/demo/guides`); a name not there falls back to its list.
 */
import { t } from "./i18n";

export type GuideId = "operator" | "process" | "control" | "maintenance" | "manager" | "it";

export type GuideStop = {
  title: string;
  body: string;
  /** The page it opens: `to`, or the page of the first of `names` the demo holds, else `to`. */
  to: string;
  names?: string[];
};

export type Guide = {
  id: GuideId;
  /** Who it is for, on the picker ("Control room operator"). */
  label: string;
  /** What they get, in one line. */
  pitch: string;
  stops: GuideStop[];
};

export const GUIDE_IDS: GuideId[] = ["operator", "process", "control", "maintenance", "manager", "it"];

/** The guides, in the current language (built when asked: `t` reads the language then). */
export function demoGuides(): Guide[] {
  return [
    {
      id: "operator",
      label: t("Control room operator"),
      pitch: t("The unit at a glance, the alarms that matter, and the team."),
      stops: [
        {
          title: t("Riverbend, from the control room"),
          body: t("You run the unit. This guide opens the screens an operator keeps in front of them: the process displays, the alarms, the wall screen, trends and the team. Use Next; the guide stays here while you look around."),
          to: "/",
        },
        {
          title: t("The process, as on the DCS"),
          body: t("The plant drawn as you know it: every loop shows its value, setpoint, output and mode, with a coloured bubble when Analytics finds it unhealthy. The buttons at the top open each unit."),
          to: "/dash/diagrams",
          names: ["Riverbend plant", "Riverbend Refinery"],
        },
        {
          title: t("Alarms, with their story"),
          body: t("The alarms of the plant's signals and of the apps' findings, by priority. Open one: its history, who acknowledged it, and the reason it was shelved."),
          to: "/alarm/alarms",
        },
        {
          title: t("The control room's wall screen"),
          body: t("The same loops on pages that turn by themselves in kiosk mode, on any screen, without signing in."),
          to: "/dash/",
          names: ["Control room"],
        },
        {
          title: t("Any signal, any period"),
          body: t("Pick the tags you watch, choose the period and keep the trend for the next shift. Everything comes from the plant's history, in seconds."),
          to: "/dash/trends",
        },
        {
          title: t("Talk about the equipment, not around it"),
          body: t("The team talks here about the FIC-1003 recycle valve. The valve specialist, an assistant the engineers set up, answers in the same conversation."),
          to: "/messages",
          names: ["FIC-1003 recycle valve"],
        },
        {
          title: t("From what you saw to what gets done"),
          body: t("Each problem becomes an action with an owner and a due date, linked to the loop and the alarm it came from. You follow it to the end, here or on your phone."),
          to: "/actions",
        },
      ],
    },
    {
      id: "process",
      label: t("Process engineer"),
      pitch: t("Find what limits the unit, and understand it with data, models and documents."),
      stops: [
        {
          title: t("Your unit, every morning"),
          body: t("Desk is where your day starts: what changed on the plant, your actions, and the apps' findings on what you follow. This guide walks one problem, the sticking FIC-1003 valve, from finding to fix."),
          to: "/",
        },
        {
          title: t("What needs attention, and why"),
          body: t("Analytics judges every loop and signal on a schedule and says why, in words: four of Riverbend's loops are in trouble. You spend your time on them, not on finding them."),
          to: "/link/executions",
        },
        {
          title: t("One loop, with its evidence"),
          body: t("FIC-1003: stiction, with the evidence that convinced the engineer: the valve's signature, the scores and the trends from the historian."),
          to: "/link/loops/FIC-1003",
        },
        {
          title: t("Try it on a model first"),
          body: t("A Models study: an optimizer tunes the level controller on a simulation before anyone touches the plant. Sizing studies and the Furnaces model that runs beside the plant live here too."),
          to: "/model/studies",
          names: ["Tune the level controller"],
        },
        {
          title: t("Ask the plant's documents"),
          body: t("Operating manuals, control narratives, datasheets and maintenance history, searched by meaning: each answer cites its page."),
          to: "/doc/search?q=stiction",
        },
        {
          title: t("The assistant, on your data"),
          body: t("A chat of the team: the assistant read FIC-1003's data and the documents and explained the cycling, with its sources. In this demo you read the chats; the people an administrator creates can ask."),
          to: "/assistant",
          names: ["Why does FIC-1003 cycle?"],
        },
        {
          title: t("Python when you need it"),
          body: t("Notebooks run Python in the browser on the plant's signals, for the analysis no app does yet."),
          to: "/notebooks",
        },
      ],
    },
    {
      id: "control",
      label: t("Control and instrumentation engineer"),
      pitch: t("Every loop watched, every finding explained, and the methods open to you."),
      stops: [
        {
          title: t("Fifty loops, watched for you"),
          body: t("Monitors run the analyses on every loop on a schedule: what runs, the queue and the latest runs. Nobody has to remember to look."),
          to: "/link/",
        },
        {
          title: t("The loops, worst first"),
          body: t("Oscillation, stiction, saturation, bad tuning and bad data, each with its severity and the sentence that explains it."),
          to: "/link/executions",
        },
        {
          title: t("A sticking valve, proven"),
          body: t("FIC-1003: Control loop performance flags stiction on its valve, and the page shows why, with the trends behind it."),
          to: "/link/loops/FIC-1003",
        },
        {
          title: t("The method is open"),
          body: t("Each algorithm is a diagram of blocks you can open and change: data check, stiction screening, valve wear. Your own methods go in the same way, in blocks or in Python."),
          to: "/link/algorithms/flow_loop/diagram",
        },
        {
          title: t("A model beside the plant"),
          body: t("The Furnaces model runs beside the plant: when TIC-1209 drifts from what the model expects, it names the thermocouple."),
          to: "/link/algorithms/example_furnaces",
        },
        {
          title: t("Alarms on findings, not only on limits"),
          body: t("Rules like \"loop critical for over an hour\" or \"valve saturated, loop off setpoint\", written as simple conditions, blocks or Python."),
          to: "/alarm/rules",
        },
        {
          title: t("And the work that follows"),
          body: t("The inspection of the FIC-1003 valve: its checklist, the test procedure it follows and the team's comments."),
          to: "/actions",
          names: ["Inspect the FIC-1003 recycle valve for stiction"],
        },
      ],
    },
    {
      id: "maintenance",
      label: t("Maintenance and reliability"),
      pitch: t("The equipment's condition, its history and the work on it, in one place."),
      stops: [
        {
          title: t("The work the plant asked for"),
          body: t("Open, under way, blocked and done: each action has an owner, a due date and the finding it came from, so nobody asks \"why are we doing this?\"."),
          to: "/actions",
        },
        {
          title: t("A repair with everything it needs"),
          body: t("The inspection of the FIC-1003 valve carries its checklist, the procedure it follows, the loop's evidence and the team's comments."),
          to: "/actions",
          names: ["Inspect the FIC-1003 recycle valve for stiction"],
        },
        {
          title: t("One page per equipment"),
          body: t("FIC-1003's record, its signals by role, what is inside it, its actions and its history, in tabs. Every app finds the same asset."),
          to: "/assets/FIC-1003",
        },
        {
          title: t("The maintenance history, searchable"),
          body: t("Which valves came back, and what was done to them: the history the team searches before a repair."),
          to: "/doc/",
          names: ["DOC-MH-001"],
        },
        {
          title: t("Condition, every month"),
          body: t("A report on the valves and instruments, sent on a schedule as a PDF: the ones getting worse, before they fail."),
          to: "/dash/reports",
          names: ["Valve and instrument health, monthly"],
        },
        {
          title: t("A case closed"),
          body: t("Last month's twin: the FIC-1102 positioner, found by Analytics, replaced and checked. The history stays with the asset."),
          to: "/actions",
          names: ["Replace the FIC-1102 valve positioner"],
        },
        {
          title: t("Everything with a date"),
          body: t("Actions, the apps' scheduled runs and the team's events in one calendar, beside your Outlook or Google calendar."),
          to: "/calendar",
        },
      ],
    },
    {
      id: "manager",
      label: t("Plant or area manager"),
      pitch: t("Where the plant stands, what the team does about it, and the trend."),
      stops: [
        {
          title: t("The plant on one screen"),
          body: t("Where the loops of each unit stand and how they moved: what an area manager looks at before the morning meeting."),
          to: "/dash/",
          names: ["Plant overview"],
        },
        {
          title: t("The week's control performance"),
          body: t("Which loops had problems this week, which problems and for how long: a report written by itself and sent by e-mail every Monday."),
          to: "/dash/reports",
          names: ["Control loops weekly performance"],
        },
        {
          title: t("Alarm load against the standard"),
          body: t("Alarms per hour, floods and the worst offenders, measured against ISA-18.2 targets."),
          to: "/alarm/performance",
        },
        {
          title: t("What the team does about it"),
          body: t("Every action with its owner and due date: what is late, what is blocked, what was done this month."),
          to: "/actions",
        },
        {
          title: t("The alarm summary, every week"),
          body: t("The week's alarms counted and ranked, so the bad actors get fixed, not lived with."),
          to: "/dash/reports",
          names: ["Alarm summary, weekly"],
        },
        {
          title: t("One suite, one login"),
          body: t("Every app of the suite on the same plant, the same people and the same assets. Your engineers add apps and methods without starting over."),
          to: "/admin",
        },
      ],
    },
    {
      id: "it",
      label: t("IT, OT and security"),
      pitch: t("What runs where, what talks to the plant, and who sees what."),
      stops: [
        {
          title: t("Everything on your server"),
          body: t("Each app is its own container on a server of the plant's network, offline: no cloud, no telemetry, no update checks. The only outbound connections are the sources the administrator configures."),
          to: "/admin",
        },
        {
          title: t("Read-only to the plant"),
          body: t("The Historian reads the plant through OPC UA (or PI) and keeps the history. No app writes to the control system: the only write path is to the simulator."),
          to: "/hist/sources",
        },
        {
          title: t("The suite's health"),
          body: t("Every app's state and version, the server's disk and memory, and the queues, on one page."),
          to: "/health",
        },
        {
          title: t("Who sees what"),
          body: t("Sign-in is on by default. Each person has a level per app (edit, read or none) and the part of the plant they work on; every change goes to an audit log. This visit is read-only."),
          to: "/people/me",
        },
        {
          title: t("The language model, only if you approve it"),
          body: t("The assistant is off until IT approves a model, a local one included. Then only the people an administrator names may ask, with the same permissions as their screens."),
          to: "/assistant",
        },
        {
          title: t("Installed in minutes, offline"),
          body: t("One bundle with every image and dependency, signed, with its SBOM; backups before every upgrade and a rollback. The installation and security guides are in Help."),
          to: "/help",
        },
      ],
    },
  ];
}

export function guideById(id: string | null | undefined): Guide | null {
  return demoGuides().find((guide) => guide.id === id) ?? null;
}

/** The page a stop opens on this installation. */
export function stopHref(stop: GuideStop, links: Record<string, string>): string {
  for (const name of stop.names ?? []) {
    const href = links[name];
    if (href && href.startsWith("/") && !href.startsWith("//")) return href;
  }
  return stop.to;
}
