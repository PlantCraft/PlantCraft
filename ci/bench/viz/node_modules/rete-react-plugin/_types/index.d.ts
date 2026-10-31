import { BaseSchemes, CanAssignSignal, Scope } from 'rete';
import { RenderPreset } from './presets/types';
import { CreateRoot, HasLegacyRender, Renderer } from './renderer';
import { Position, RenderSignal } from './types';
export * as Presets from './presets';
export type { ClassicScheme, ReactArea2D, RenderEmit } from './presets/classic';
export { RefComponent } from './ref-component';
export * from './shared';
export * from './types';
export { useRete } from './utils';
/**
 * Signals that can be emitted by the plugin
 * @priority 9
 */
export type Produces<Schemes extends BaseSchemes> = {
    type: 'connectionpath';
    data: {
        payload: Schemes['Connection'];
        path?: string;
        points: Position[];
    };
};
type Requires<Schemes extends BaseSchemes> = RenderSignal<'node', {
    payload: Schemes['Node'];
}> | RenderSignal<'connection', {
    payload: Schemes['Connection'];
    start?: Position;
    end?: Position;
}> | {
    type: 'unmount';
    data: {
        element: HTMLElement;
    };
};
/**
 * Plugin props
 */
export type Props = HasLegacyRender extends true ? {
    /** root factory for React.js 18+ */
    createRoot?: CreateRoot;
} : {
    createRoot: CreateRoot;
};
/**
 * React plugin. Renders nodes, connections and other elements using React.
 * @priority 10
 * @emits connectionpath
 * @listens render
 * @listens unmount
 */
export declare class ReactPlugin<Schemes extends BaseSchemes, T = Requires<Schemes>> extends Scope<Produces<Schemes>, [Requires<Schemes> | T]> {
    renderer: Renderer;
    presets: RenderPreset<Schemes, T>[];
    constructor(...[props]: HasLegacyRender extends true ? [props?: Props] : [props: Props]);
    setParent(scope: Scope<Requires<Schemes> | T>): void;
    private mount;
    private unmount;
    /**
     * Adds a preset to the plugin.
     * @param preset Preset that can render nodes, connections and other elements.
     */
    addPreset<K>(preset: RenderPreset<Schemes, CanAssignSignal<T, K> extends true ? K : 'Cannot apply preset. Provided signals are not compatible'>): void;
}
//# sourceMappingURL=index.d.ts.map