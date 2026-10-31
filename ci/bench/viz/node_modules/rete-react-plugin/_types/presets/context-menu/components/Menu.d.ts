import * as React from 'react';
import { Customize, Item } from '../types';
export declare const Styles: import("styled-components/dist/types").IStyledComponentBase<"web", import("styled-components").FastOmit<React.DetailedHTMLProps<React.HTMLAttributes<HTMLDivElement>, HTMLDivElement>, never>> & string;
type Props = {
    items: Item[];
    delay: number;
    searchBar?: boolean;
    onHide(): void;
    components?: Customize;
};
export declare function Menu(props: Props): React.JSX.Element;
export {};
//# sourceMappingURL=Menu.d.ts.map