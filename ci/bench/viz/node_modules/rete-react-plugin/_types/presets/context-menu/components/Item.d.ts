import * as React from 'react';
import { Customize, Item } from '../types';
export declare const ItemStyle: import("styled-components/dist/types").IStyledComponentBase<"web", any> & string;
export declare const SubitemStyles: import("styled-components/dist/types").IStyledComponentBase<"web", import("styled-components").FastOmit<React.DetailedHTMLProps<React.HTMLAttributes<HTMLDivElement>, HTMLDivElement>, never>> & string;
type Props = {
    data: Item;
    delay: number;
    hide(): void;
    children: React.ReactNode;
    components?: Pick<Customize, 'item' | 'subitems'>;
};
export declare function ItemElement(props: Props): React.JSX.Element;
export {};
//# sourceMappingURL=Item.d.ts.map