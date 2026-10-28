within PlantCraftSources;
block Sine "Sine wave: a value that oscillates"
  parameter Real amplitude = 1 "Amplitude";
  parameter Real f(unit = "Hz", min = 0) = 0.01 "Frequency";
  parameter Real phase(unit = "rad") = 0 "Phase at startTime";
  parameter Real offset = 0 "Mean value";
  parameter Real startTime(unit = "s") = 0 "When the wave starts";
  Modelica.Blocks.Interfaces.RealOutput y "Value"
    annotation(Placement(transformation(extent = {{100, -10}, {120, 10}}), iconTransformation(extent = {{100, -10}, {120, 10}})));
equation
  y = offset + (if time < startTime then 0 else amplitude * sin(2 * Modelica.Constants.pi * f * (time - startTime) + phase));
  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "Sine", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>A value that oscillates, to test how a model answers a periodic disturbance.</p><h4>How to read it</h4><p>The output swings by amplitude around offset with frequency f (one cycle every 1/f seconds), from startTime on.</p><h4>Formula</h4><pre>y = offset + amplitude·sin(2π·f·(t − startTime) + phase)</pre></html>"));
end Sine;
