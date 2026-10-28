/** The icons an asset type may use: process symbols drawn here (valve, pump, vessel, column,
 * exchanger, compressor, tank, instrument), in the same line style as the interface's other
 * icons, and a catalog of common ones, grouped. A type stores the icon's name only. */
import {
  Activity, AirVent, Anchor, Antenna, Archive, ArrowLeftRight, AudioWaveform, Battery, BatteryCharging, Bell, Biohazard, Bolt, Bot, Box, Boxes, Briefcase, Building, Building2, Cable, Camera, Car, Cctv, CircleDot, CircuitBoard, Clipboard, Cloud, CloudRain, Cog, Cone, Construction, Container, CookingPot, Cpu, Crosshair, Cuboid, Cylinder, Database, Disc3, Droplet, Droplets, Factory, Fan, FileText, Flag, FlaskConical, FlaskRound, Flame, FlameKindling, Folder, Forklift, Fuel, Gauge, GitBranch, HardDrive, HardHat, Heater, Hexagon, Home, Landmark, Layers, LayoutGrid, Leaf, Lightbulb, MapPin, Map as MapIcon, Magnet, Merge, Microscope, Monitor, Mountain, Network, Nut, Orbit, Package, Pickaxe, Pipette, Plug, PlugZap, Power, Radar, Radio, Recycle, RefreshCw, Rocket, Route, Router, Ruler, Satellite, Scale, Server, Settings, Shapes, ShieldAlert, ShieldCheck, Ship, Signal, Siren, SlidersHorizontal, Snowflake, Split, Sprout, Sun, Target, TestTube, TestTubes, Thermometer, ThermometerSnowflake, ThermometerSun, Timer, Tornado, Train, Trees, TriangleAlert, Truck, Users, Warehouse, Waves, Waypoints, Wheat, Wifi, Wind, Workflow, Wrench, Zap,
} from "lucide-react";
import type { ComponentType, ReactNode } from "react";
import { t } from "./i18n";

type IconProps = { size?: number };

/** A process symbol in the interface's line style (24 by 24, 2 px round strokes). */
function symbol(paths: ReactNode): ComponentType<IconProps> {
  return function ProcessSymbol({ size = 15 }: IconProps) {
    return <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths}</svg>;
  };
}

/** P&ID-like symbols (ISA-5.1 shapes, drawn here): the ones process plants need most. */
export const PROCESS_SYMBOLS: Record<string, ComponentType<IconProps>> = {
  valve: symbol(<><path d="M3 8v8l9-4z" /><path d="M21 8v8l-9-4z" /><path d="M12 12V5" /><path d="M9 5h6" /></>),
  pump: symbol(<><circle cx="11" cy="13" r="7" /><path d="M11 6h10v4" /><path d="M6 21h10" /></>),
  vessel: symbol(<><rect x="7" y="2" width="10" height="20" rx="5" /><path d="M7 15h10" /></>),
  column: symbol(<><rect x="8" y="2" width="8" height="20" rx="4" /><path d="M8 8h5" /><path d="M11 12h5" /><path d="M8 16h5" /></>),
  exchanger: symbol(<><circle cx="12" cy="12" r="9" /><path d="M3 12h3l2-4 4 8 4-8 2 4h3" /></>),
  compressor: symbol(<><path d="M4 5l16 4v6L4 19z" /></>),
  tank: symbol(<><path d="M4 9c0-2 3.6-4 8-4s8 2 8 4v11H4z" /><path d="M4 14h16" /></>),
  instrument: symbol(<><circle cx="12" cy="12" r="8" /><path d="M4 12h16" /></>),
  drum: symbol(<><rect x="2" y="7" width="20" height="10" rx="5" /><path d="M8 17v3" /><path d="M16 17v3" /></>),
  filter: symbol(<><path d="M6 3h12v18H6z" /><path d="M6 3l12 18" /></>),
  reactor: symbol(<><rect x="6" y="2" width="12" height="20" rx="6" /><path d="M9 8l6 4-6 4" /></>),
};

export interface IconGroup { label: string; icons: Record<string, ComponentType<IconProps>> }

/** Every icon a type may use, in the groups the picker shows. */
export const ICON_GROUPS: IconGroup[] = [
  { label: t("Process equipment"), icons: { ...PROCESS_SYMBOLS, box: Box, boxes: Boxes, package: Package, cylinder: Cylinder, container: Container, archive: Archive, cuboid: Cuboid, cone: Cone, hexagon: Hexagon, shapes: Shapes, "cooking-pot": CookingPot } },
  { label: t("Heat and flow"), icons: { flame: Flame, "flame-kindling": FlameKindling, heater: Heater, "thermometer-sun": ThermometerSun, "thermometer-snowflake": ThermometerSnowflake, thermometer: Thermometer, snowflake: Snowflake, fan: Fan, wind: Wind, "air-vent": AirVent, droplet: Droplet, droplets: Droplets, waves: Waves, tornado: Tornado, fuel: Fuel, "arrow-left-right": ArrowLeftRight, merge: Merge, split: Split, recycle: Recycle, "refresh-cw": RefreshCw } },
  { label: t("Instruments and control"), icons: { gauge: Gauge, activity: Activity, "audio-waveform": AudioWaveform, timer: Timer, ruler: Ruler, scale: Scale, crosshair: Crosshair, target: Target, "circle-dot": CircleDot, radar: Radar, "sliders-horizontal": SlidersHorizontal, settings: Settings, cog: Cog, cpu: Cpu, "circuit-board": CircuitBoard, monitor: Monitor, cctv: Cctv, camera: Camera, bot: Bot, workflow: Workflow, "git-branch": GitBranch } },
  { label: t("Electrical"), icons: { zap: Zap, bolt: Bolt, plug: Plug, "plug-zap": PlugZap, power: Power, battery: Battery, "battery-charging": BatteryCharging, cable: Cable, lightbulb: Lightbulb, magnet: Magnet, orbit: Orbit, "disc-3": Disc3, nut: Nut, wrench: Wrench } },
  { label: t("Lab and quality"), icons: { "flask-conical": FlaskConical, "flask-round": FlaskRound, "test-tube": TestTube, "test-tubes": TestTubes, pipette: Pipette, microscope: Microscope, biohazard: Biohazard } },
  { label: t("Sites and buildings"), icons: { building: Building2, "building-1": Building, factory: Factory, warehouse: Warehouse, landmark: Landmark, home: Home, "map-pin": MapPin, map: MapIcon, flag: Flag, construction: Construction, "hard-hat": HardHat, mountain: Mountain, trees: Trees, leaf: Leaf, sprout: Sprout, wheat: Wheat, sun: Sun, cloud: Cloud, "cloud-rain": CloudRain, pickaxe: Pickaxe } },
  { label: t("Transport and logistics"), icons: { truck: Truck, train: Train, ship: Ship, anchor: Anchor, car: Car, forklift: Forklift, route: Route, waypoints: Waypoints, rocket: Rocket } },
  { label: t("IT and communication"), icons: { server: Server, database: Database, "hard-drive": HardDrive, network: Network, router: Router, wifi: Wifi, antenna: Antenna, radio: Radio, satellite: Satellite, signal: Signal, layers: Layers, "layout-grid": LayoutGrid, folder: Folder, "file-text": FileText, clipboard: Clipboard } },
  { label: t("Safety and people"), icons: { "shield-check": ShieldCheck, "shield-alert": ShieldAlert, "triangle-alert": TriangleAlert, siren: Siren, bell: Bell, users: Users, briefcase: Briefcase } },
];

/** Every icon by name; the names types stored before keep their drawings. */
export const TYPE_ICONS: Record<string, ComponentType<IconProps>> = Object.assign({}, ...ICON_GROUPS.map((group) => group.icons));
