import { Scope } from 'rete';
import { SocketPositionWatcher } from 'rete-render-utils';
import { RenderPreset } from '../types';
import { ClassicScheme, ExtractPayload, ReactArea2D, RenderEmit } from './types';
import { AcceptComponent } from './utility-types';
export { Connection } from './components/Connection';
export { useConnection } from './components/ConnectionWrapper';
export { Control } from './components/Control';
export { Control as InputControl } from './components/Control';
export { Node, NodeStyles } from './components/Node';
export { RefControl } from './components/refs/RefControl';
export { RefSocket } from './components/refs/RefSocket';
export { Socket } from './components/Socket';
export type { ClassicScheme, ReactArea2D, RenderEmit } from './types';
export * as vars from './vars';
type CustomizationProps<Schemes extends ClassicScheme> = {
    node?: (data: ExtractPayload<Schemes, 'node'>) => AcceptComponent<typeof data['payload'], {
        emit: RenderEmit<Schemes>;
    }> | null;
    connection?: (data: ExtractPayload<Schemes, 'connection'>) => AcceptComponent<typeof data['payload']> | null;
    socket?: (data: ExtractPayload<Schemes, 'socket'>) => AcceptComponent<typeof data['payload']> | null;
    control?: (data: ExtractPayload<Schemes, 'control'>) => AcceptComponent<typeof data['payload']> | null;
};
type ClassicProps<Schemes extends ClassicScheme, K> = {
    socketPositionWatcher?: SocketPositionWatcher<Scope<never, [K]>>;
    customize?: CustomizationProps<Schemes>;
};
/**
 * Classic preset for rendering nodes, connections, controls and sockets.
 */
export declare function setup<Schemes extends ClassicScheme, K extends ReactArea2D<Schemes>>(props?: ClassicProps<Schemes, K>): RenderPreset<Schemes, K>;
//# sourceMappingURL=index.d.ts.map