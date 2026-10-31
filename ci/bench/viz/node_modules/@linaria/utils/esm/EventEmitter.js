export class EventEmitter {
  static dummy = new EventEmitter(() => {});
  constructor(onEvent) {
    this.onEvent = onEvent;
  }
  pair(labels) {
    this.onEvent(labels, 'start');
    return () => {
      this.onEvent(labels, 'finish');
    };
  }
  single(labels) {
    this.onEvent(labels, 'single');
  }
}
//# sourceMappingURL=EventEmitter.js.map