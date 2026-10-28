# Getting started

An hour with the demo plant, app by app. You will follow one problem, a sticky valve, from the
signal to the alarm, the dashboard, a model and a notebook, and see how the apps of the suite
hand it to each other. You need an installation with the demo story (`./install.sh --all-apps
--demo`, see [Install PlantCraft](../install.md)) and the administrator's password.

## The plant and the story

The demo plant is the **Simulator**: an OPC UA server of 50 control loops in two units, U-100 and
U-200, with faults it simulates on purpose. Four valves stick (FIC-1003, FIC-1102, FIC-1206,
FIC-1214), some pressure and temperature loops oscillate (PIC-1002, PIC-1202), the furnace outlet
temperature TIC-1209 drifts, and TIC-1104 sees a cyclic disturbance.

The story fills the suite as if a team had used it for three weeks: Ana Lima, the process
engineer, a technician, operators and a supervisor, their conversations and actions, monitors
already running, dashboards, alarm rules, model studies, and the assistant chats they kept. The
demo visitor takes part in the team's conversations in Messages.

## 1. Sign in and find your day (Desk)

Open the suite's address and sign in as `admin`. You land in **Desk**, each person's day:

- **Today** gathers what needs you: notifications, actions assigned to you, the day's events and
  widgets you choose. **Customize** moves and adds widgets.
- **Actions** holds the follow-ups the team opened, such as *Inspect the FIC-1003 recycle valve
  for stiction*. Open one to see its target, its owner and its history.
- **Calendar**, **To-do**, **Notes** and **Team** are the rest of the day: meetings, your own
  list, notes and who is on shift.

At the bottom of the sidebar are the four quick buttons every app shares: **Messages**
(conversations with people and specialists), **Notifications** (what needs a person),
**Assistant** (the AI chat of the page you are on) and **Queue** (what is running in the
background, app by app).

## 2. The plant's map (PlantCraft)

Open **PlantCraft** in the app menu, then **Assets**. The tree is the plant: the site, its units,
areas, equipment and loops. Open **FIC-1003**: its signals are listed by **role** (the loop's
`pv`, `sp` and `op`), so every app knows which signal is the measurement and which is the valve
output without being told again.

Every app reads the same tree. When you add a unit or a loop here, Analytics, Alarms and View see
it at once. A whole plant map can be loaded from Excel or JSON
([Configuration file](configuration-file.md)).

## 3. The data (Historian)

Open **Historian**. **Sources** lists where the data comes from: here, the Simulator's OPC UA
server; at a plant, a PI Web API, OPC UA, MQTT, Modbus TCP, SQL or CSV source. **Signals** lists
every signal archived, with its scan and compression settings. Open `FIC-1003.OP` and look at a
day of it: the valve output moves in steps instead of smoothly, the first sign of stiction.

The Historian is read-only toward the plant. **Calculated signals** derive new signals from
others (a difference, a ratio, a filter), **Imports** brings files in once or every time they
land in a folder, and **Exports** takes data out to CSV.

## 4. Watching the loops (Analytics)

Open **Analytics**. It runs **algorithms**, made of **blocks**, on the plant's assets and
signals, and publishes **results**: a level (OK, Warning, Critical or Unknown), a score from 0
to 100 and a sentence that says why.

1. **Monitors** lists what runs on its own: *Control loop performance* judges every loop,
   *Signal quality* every signal, and *Furnaces* runs the furnaces' model beside the plant.
2. **Results** shows what they concluded, by monitor, then by target, then over time. Open
   FIC-1003: its result names stiction and shows the evidence, the trend and the valve's
   signature.
3. **Algorithms** shows how a result is reached. Open *Flow loop* and the editor draws it as
   blocks wired together. **Test** runs it on a loop now, without saving anything; **Copy as
   prompt** turns it into a prompt to review or extend it with any AI assistant.
4. The furnace model is an algorithm too: a process model beside the plant that says when the
   measured TIC-1209 drifts away from what the model predicts.

Analytics never touches the plant. It reads, judges and says so, and when it cannot judge (a
frozen signal, a gap, too little movement) it says Unknown and why, instead of guessing.

## 5. Alarms

Open **Alarms**. **Rules** turn signals and Analytics' results into alarms and alerts, in the
words of ISA-18.2: a rule is **Simple** (a limit with a deadband and a delay), **Blocks** or
**Python**. Open *PIC-1202 pressure high* or *Loop critical for over 1 h* to see each kind.

- **Alarms** is the list of what is active now. **Acknowledge** one; **Shelve** hides it for a
  while with a reason. An alarm also arrives in **Notifications**, with the same buttons.
- **Events** lists what the apps published (a result that changed level, a run that failed) and
  turns one into a rule with a click.
- **History** holds the journal, what was sent, and **Performance**: alarms per hour, floods,
  the bad actors, the standing alarms, against the ISA-18.2 targets.

## 6. Dashboards, reports and trends (View)

Open **View**. **Dashboards** are made of **panels** (stat, gauge, trend, bar chart, table,
scatter, text):

- *Plant overview* has a **public link**: anyone with it sees the dashboard without signing in,
  read-only.
- *Control room* turns its three pages every minute, for a wall screen.
- *Loop detail* has a **variable**: choose another loop at the top and every panel follows.

**Trends** draws any signals over any period and saves the view. **Reports** turns a dashboard
into a document on a schedule (*U-100 daily report*, *Control loops weekly performance*) and
exports it as Word, HTML or Markdown.

## 7. Models and simulations (Models)

Open **Models**. A model is a **block diagram** (Modelica underneath) that you draw from the
library or write as code.

1. **Models** lists the examples. Open the tank: drag a block, wire it, change a parameter.
2. **Simulate** starts a **simulation**; **Simulations** lists every simulation and the queue.
   One of the story's simulations is fed with the last hour of a real loop and compared with it.
3. **Studies** run a model many times (**New study**). *Tank size* and *Heat exchanger area*
   vary a parameter over a grid; open one and compare the curves.
4. **Export FMU** packs a model so Analytics can run it beside the plant, as the furnace example
   does.

Heavy work runs on **compute workers**, away from the apps: an administrator sees them in
Settings › Compute and can add machines ([Compute workers](../compute.md)).

## 8. Notebooks

Open **Notebooks** for Python with the plant's data: JupyterLab in the browser, or the same
notebook on your own computer with the PlantCraft Notebooks kit. The examples read signals from
the Historian, results from Analytics and simulations from Models with a few lines, as the person
who runs them ([Notebooks](notebooks.md)).

## 9. Ask the assistant

On any page, the **Assistant** button offers that page's **tasks** first: *Why did this alarm
fire?* on an alarm, *Which alarms should we fix first?* on Performance, *Explain this dashboard*
in View, *Help me create a new block* in Analytics. It reads only what you may read, through the same API and permissions you have, and it
never writes: a creation comes back as a proposal you confirm.

The assistant needs a language model, and the suite ships with none turned on. Until an
administrator sets one up in Settings › Language models, the panel says so, and the Valve
specialist in Messages answers with scripted replies. See [the assistant](../assistant.md).

## 10. Make it yours

| To | Go to |
|---|---|
| Connect your plant | Historian › Sources, then PlantCraft › Assets ([User guide](user-guide.md)) |
| Load the plant map from a spreadsheet | [Configuration file](configuration-file.md) |
| Add people, groups and who opens which app | PlantCraft › People ([User guide](user-guide.md)) |
| Put your own algorithm on your loops | Analytics › Algorithms › New, then Monitors › New |
| Back up, update, check the certificates | [Running the suite](running-the-suite.md) |
| Build an app of your own | The [app template](../../templates/app) |

The words used here are defined once in the [glossary](../glossary.md); the ideas behind them are
in [Concepts](concepts.md).
