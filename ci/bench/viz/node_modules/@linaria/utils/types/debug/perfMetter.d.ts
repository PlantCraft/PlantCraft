import { EventEmitter } from '../EventEmitter';
export interface IPerfMeterOptions {
    filename?: string;
    print?: boolean;
}
export interface IProcessedEvent {
    type: 'dependency';
    file: string;
    only: string[];
    imports: {
        from: string;
        what: string[];
    }[];
}
export declare const createPerfMeter: (options?: IPerfMeterOptions | boolean) => {
    emitter: EventEmitter;
    onDone: (sourceRoot: string) => void;
};
