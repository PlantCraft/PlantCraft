import * as React from 'react';
import { ClassicPreset, NodeId } from 'rete';
import { ClassicScheme, ReactArea2D, Side } from '../../types';
type Props<Scheme extends ClassicScheme> = {
    name: string;
    emit: (props: ReactArea2D<Scheme>) => void;
    side: Side;
    nodeId: NodeId;
    socketKey: string;
    payload: ClassicPreset.Socket;
};
export declare function RefSocket<Scheme extends ClassicScheme>({ name, emit, nodeId, side, socketKey, payload, ...props }: Props<Scheme>): React.JSX.Element;
export {};
//# sourceMappingURL=RefSocket.d.ts.map