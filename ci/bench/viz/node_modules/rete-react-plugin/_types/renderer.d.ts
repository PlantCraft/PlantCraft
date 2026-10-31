import * as React from 'react';
import * as ReactDOM from 'react-dom';
interface Root {
    render(children: React.ReactNode): void;
    unmount(): void;
}
export type HasLegacyRender = (typeof ReactDOM) extends {
    render(...args: any[]): any;
} ? true : false;
export type CreateRoot = (container: Element | DocumentFragment) => Root;
type ReactDOMRenderer = (element: React.ReactElement, container: HTMLElement) => React.Component | Element;
export type Renderer = {
    mount: ReactDOMRenderer;
    unmount: (container: HTMLElement) => void;
};
export declare function getRenderer(props?: {
    createRoot?: CreateRoot;
}): Renderer;
export {};
//# sourceMappingURL=renderer.d.ts.map