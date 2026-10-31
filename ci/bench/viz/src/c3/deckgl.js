import { Deck, OrthographicView } from "@deck.gl/core";
import { ScatterplotLayer } from "@deck.gl/layers";
import { main, num, root, timed, frames } from "../harness.js";
import { cloud } from "./common.js";
main(async () => {
  const n = num("n", 100000);
  const { x, y } = cloud(n);
  const el = root();
  const positions = new Float32Array(n * 2);
  for (let i = 0; i < n; i++) { positions[2 * i] = x[i]; positions[2 * i + 1] = -y[i]; }
  let deck, drawn;
  const render = await timed(() => new Promise((ok) => {
    deck = new Deck({ parent: el, views: new OrthographicView(), controller: true, initialViewState: { target: [50, -50, 0], zoom: 2.5 },
      onAfterRender: () => { if (!drawn) { drawn = true; ok(); } },
      layers: [new ScatterplotLayer({ id: "s", data: { length: n, attributes: { getPosition: { value: positions, size: 2 } } }, getRadius: 1, radiusUnits: "pixels", getFillColor: [37, 99, 235, 140] })] });
  }));
  const zoom = await timed(async () => { deck.setProps({ viewState: { target: [45, -45, 0], zoom: 5 } }); await frames(1); });
  deck.setProps({ viewState: { target: [50, -50, 0], zoom: 2.5 } });
  return { render, zoom, note: "no axes: deck.gl draws points only" };
});
