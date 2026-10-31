export declare class EventEmitter {
    protected onEvent: (labels: Record<string, unknown>, type: 'start' | 'finish' | 'single', event?: unknown) => void;
    static dummy: EventEmitter;
    constructor(onEvent: (labels: Record<string, unknown>, type: 'start' | 'finish' | 'single', event?: unknown) => void);
    pair(labels: Record<string, string>): () => void;
    single(labels: Record<string, unknown>): void;
}
