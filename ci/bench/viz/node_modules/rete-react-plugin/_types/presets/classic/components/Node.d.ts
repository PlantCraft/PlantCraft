import * as React from 'react';
import { ClassicScheme, RenderEmit } from '../types';
type NodeExtraData = {
    width?: number;
    height?: number;
};
export declare const NodeStyles: import("styled-components/dist/types").IStyledComponentBase<"web", import("styled-components/dist/types").Substitute<React.DetailedHTMLProps<React.HTMLAttributes<HTMLDivElement>, HTMLDivElement>, NodeExtraData & {
    selected: boolean;
    styles?: (props: any) => any;
}>> & string;
type Props<S extends ClassicScheme> = {
    data: S['Node'] & NodeExtraData;
    styles?: () => any;
    emit: RenderEmit<S>;
};
export type NodeComponent<Scheme extends ClassicScheme> = (props: Props<Scheme>) => JSX.Element;
export declare function Node<Scheme extends ClassicScheme>(props: Props<Scheme>): React.JSX.Element;
export {};
//# sourceMappingURL=Node.d.ts.map