// deck.gl
// SPDX-License-Identifier: MIT
// Copyright (c) vis.gl contributors
import assert from "../utils/assert.js";
import { DEFAULT_CANVAS_ID } from "./view-manager.js";
/**
 * Owns resources derived from a `Deck._canvases` configuration.
 *
 * The existing single-canvas path stays in Deck. This class only reconciles presentation
 * canvases, their {@link PresentationContext}s and per-canvas {@link EventManager}s, and answers
 * geometry queries for those targets.
 * @internal
 */
export default class CanvasManager {
    /** Configure event-manager creation and root lookup supplied by the owning Deck instance. */
    constructor(props) {
        /** Active canvas entries keyed by canvas id. */
        this.targets = {};
        /** Canvas ids in presentation order. */
        this.order = [];
        /** Event managers keyed by canvas id. */
        this.eventManagers = {};
        /** Associate event roots and canvas elements with their presentation canvas id. */
        this._eventRootToCanvasId = new WeakMap();
        this._createEventManager = props.createEventManager;
        this._getEventRoot = props.getEventRoot;
    }
    /** Destroy all presentation contexts and event managers. */
    finalize() {
        for (const target of Object.values(this.targets)) {
            target.eventManager.destroy();
            target.presentationContext.destroy();
        }
        this.targets = {};
        this.order = [];
        this.eventManagers = {};
        this._eventRootToCanvasId = new WeakMap();
    }
    /**
     * Diff the configured presentation canvases against the current registry and create, reuse,
     * or destroy canvas targets as needed.
     */
    syncCanvasEntries(props) {
        const normalizedCanvases = this._normalizeCanvasList(props.canvases);
        const nextTargets = {};
        const nextOrder = [];
        const eventRootCounts = new Map();
        for (const { canvas } of normalizedCanvases) {
            const eventRoot = this._getEventRoot(canvas);
            eventRootCounts.set(eventRoot, (eventRootCounts.get(eventRoot) || 0) + 1);
        }
        for (const { id, canvas } of normalizedCanvases) {
            const resolvedEventRoot = this._getEventRoot(canvas);
            // A shared event root would dispatch every event to every target's controller. In that
            // ambiguous case, listen directly on each canvas to keep input local to its target.
            const eventRoot = eventRootCounts.get(resolvedEventRoot) === 1 ? resolvedEventRoot : canvas;
            let target = this.targets[id];
            if (!target ||
                target.device !== props.device ||
                target.canvas !== canvas ||
                target.eventRoot !== eventRoot) {
                target?.eventManager.destroy();
                target?.presentationContext.destroy();
                const presentationContext = props.device.createPresentationContext({
                    id,
                    canvas,
                    useDevicePixels: props.useDevicePixels,
                    autoResize: true
                });
                target = {
                    id,
                    device: props.device,
                    canvas,
                    eventRoot,
                    presentationContext,
                    eventManager: this._createEventManager(eventRoot)
                };
            }
            this._eventRootToCanvasId.set(eventRoot, id);
            this._eventRootToCanvasId.set(canvas, id);
            nextTargets[id] = target;
            nextOrder.push(id);
        }
        for (const [id, target] of Object.entries(this.targets)) {
            if (!nextTargets[id]) {
                target.eventManager.destroy();
                target.presentationContext.destroy();
            }
        }
        this.targets = nextTargets;
        this.order = nextOrder;
        const nextEventManagers = Object.fromEntries(Object.entries(nextTargets).map(([id, target]) => [id, target.eventManager]));
        if (!this._haveSameEventManagers(nextEventManagers)) {
            this.eventManagers = nextEventManagers;
        }
    }
    /** Resolve the presentation canvas id that produced a DOM event. */
    getCanvasIdFromEvent(rootElement) {
        return rootElement ? this._eventRootToCanvasId.get(rootElement) : undefined;
    }
    /** Look up a canvas target by id, defaulting to the first configured canvas. */
    getTarget(canvasId) {
        return this.targets[canvasId || this.order[0] || DEFAULT_CANVAS_ID] || null;
    }
    /** Resolve DOM element ids and reject duplicate presentation-canvas ids. */
    _normalizeCanvasList(canvases = []) {
        const ids = new Set();
        return canvases.map((canvasLike, index) => {
            let canvas;
            let id;
            if (typeof canvasLike === 'string') {
                canvas = document.getElementById(canvasLike);
                assert(canvas, `Canvas with id ${canvasLike} not found`);
                id = canvasLike;
            }
            else {
                canvas = canvasLike;
                id = canvas.id || `deckgl-canvas-${index}`;
            }
            assert(!ids.has(id), `Duplicate canvas id ${id}`);
            ids.add(id);
            return { id, canvas };
        });
    }
    /** Preserve manager-map identity when an update retains the same event managers. */
    _haveSameEventManagers(eventManagers) {
        const eventManagerIds = Object.keys(eventManagers);
        const previousEventManagerIds = Object.keys(this.eventManagers);
        return (eventManagerIds.length === previousEventManagerIds.length &&
            eventManagerIds.every(id => eventManagers[id] === this.eventManagers[id]));
    }
}
//# sourceMappingURL=canvas-manager.js.map