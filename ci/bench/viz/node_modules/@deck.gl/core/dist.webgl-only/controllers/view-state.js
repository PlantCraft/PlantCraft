// deck.gl
// SPDX-License-Identifier: MIT
// Copyright (c) vis.gl contributors
/** Carries a zoom anchor until constraints have selected the displayed scale. */
export const CONSTRAINT_AROUND = Symbol('constraintAround');
export default class ViewState {
    constructor(props, state, makeViewport, constraintContext) {
        this.makeViewport = makeViewport;
        this._viewportProps = this.applyConstraints(props, constraintContext);
        this._state = state;
    }
    getViewportProps() {
        return this._viewportProps;
    }
    getState() {
        return this._state;
    }
}
//# sourceMappingURL=view-state.js.map