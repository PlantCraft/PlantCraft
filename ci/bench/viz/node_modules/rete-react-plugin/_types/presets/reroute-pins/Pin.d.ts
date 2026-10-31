import * as React from 'react';
import { Position } from '../../types';
import { Pin as PinType } from './types';
type Props = PinType & {
    contextMenu(): void;
    translate(dx: number, dy: number): void;
    pointerdown(): void;
    pointer(): Position;
};
export declare function Pin(props: Props): React.JSX.Element;
export {};
//# sourceMappingURL=Pin.d.ts.map