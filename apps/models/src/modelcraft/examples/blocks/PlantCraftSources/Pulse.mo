within PlantCraftSources;
block Pulse "Pulse train: a value switched on and off periodically"
  parameter Real amplitude = 1 "Value added while on";
  parameter Real period(unit = "s", min = 1e-6) = 60 "Time between pulses";
  parameter Real width(min = 0, max = 100) = 50 "Share of each period the pulse is on (%)";
  parameter Real offset = 0 "Value while off";
  parameter Real startTime(unit = "s") = 0 "When the first pulse starts";
  Modelica.Blocks.Interfaces.RealOutput y "Value"
    annotation(Placement(transformation(extent = {{100, -10}, {120, 10}}), iconTransformation(extent = {{100, -10}, {120, 10}})));
equation
  y = offset + (if time < startTime then 0 elseif mod(time - startTime, period) < width / 100 * period then amplitude else 0);
  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "Pulse", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>A value switched on and off periodically, as a batch feed or an intermittent load.</p><h4>How to read it</h4><p>From startTime on, the output is offset + amplitude during the first width % of each period and offset the rest of it.</p><h4>Formula</h4><pre>y = offset + amplitude while mod(t − startTime, period) &lt; width/100·period, else offset</pre></html>"));
end Pulse;
