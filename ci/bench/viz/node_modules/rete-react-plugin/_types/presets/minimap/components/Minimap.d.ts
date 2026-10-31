import * as React from 'react';
import { Rect, Transform, Translate } from '../types';
type Props = {
    size: number;
    ratio: number;
    nodes: Rect[];
    viewport: Rect;
    start(): Transform;
    translate: Translate;
    point(x: number, y: number): void;
};
export declare function Minimap(props: Props): React.JSX.Element;
export {};
//# sourceMappingURL=Minimap.d.ts.map