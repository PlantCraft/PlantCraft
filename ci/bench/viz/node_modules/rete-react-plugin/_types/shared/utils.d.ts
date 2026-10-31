export declare function copyEvent<T extends Event & Record<string, any>>(e: T): T;
declare const rootPrefix = "__reactContainer$";
type Keys = `${typeof rootPrefix}${string}` | '_reactRootContainer';
type ReactNode = Partial<Record<Keys, unknown>> & HTMLElement;
export declare function findReactRoot(element: HTMLElement): ReactNode | undefined;
export {};
//# sourceMappingURL=utils.d.ts.map