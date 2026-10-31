import * as React from 'react';
export declare function Root({ children, rendered }: {
    children: React.JSX.Element | null;
    rendered: () => void;
}): React.JSX.Element | null;
export declare function syncFlush(): {
    apply(f: () => void): void;
};
export declare function useRete<T extends {
    destroy(): void;
}>(create: (el: HTMLElement) => Promise<T>): readonly [React.RefObject<HTMLDivElement>, T | null];
//# sourceMappingURL=utils.d.ts.map