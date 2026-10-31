import * as React from 'react';
import { Position } from '../types';
type Translate = (dx: number, dy: number) => void;
type StartEvent = {
    pageX: number;
    pageY: number;
};
export declare function useDrag(translate: Translate, getPointer: (e: StartEvent) => Position): {
    start(e: StartEvent): void;
};
export declare function useNoDrag(ref: React.MutableRefObject<HTMLElement | null>, disabled?: boolean): void;
export declare function NoDrag(props: {
    children: React.ReactNode;
    disabled?: boolean;
}): React.JSX.Element;
export {};
//# sourceMappingURL=drag.d.ts.map