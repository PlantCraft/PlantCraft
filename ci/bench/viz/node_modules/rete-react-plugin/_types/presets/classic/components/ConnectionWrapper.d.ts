import * as React from 'react';
import { Position } from '../../../types';
export type ConnectionContextValue = {
    start: Position | null;
    end: Position | null;
    path: null | string;
};
export declare const ConnectionContext: React.Context<ConnectionContextValue>;
type PositionWatcher = (cb: (value: Position) => void) => (() => void);
type Props = {
    children: React.JSX.Element;
    start: Position | PositionWatcher;
    end: Position | PositionWatcher;
    path(start: Position, end: Position): Promise<null | string>;
};
export declare function ConnectionWrapper(props: Props): React.JSX.Element;
export declare function useConnection(): ConnectionContextValue;
export {};
//# sourceMappingURL=ConnectionWrapper.d.ts.map