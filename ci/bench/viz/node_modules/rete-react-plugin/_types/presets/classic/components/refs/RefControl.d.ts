import * as React from 'react';
import { ClassicPreset } from 'rete';
import { ClassicScheme, ReactArea2D } from '../../types';
type Props<Scheme extends ClassicScheme> = {
    name: string;
    emit: (props: ReactArea2D<Scheme>) => void;
    payload: ClassicPreset.Control;
};
export declare function RefControl<Scheme extends ClassicScheme>({ name, emit, payload, ...props }: Props<Scheme>): React.JSX.Element;
export {};
//# sourceMappingURL=RefControl.d.ts.map