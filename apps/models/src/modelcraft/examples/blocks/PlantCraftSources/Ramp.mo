within PlantCraftSources;
block Ramp "Ramp: a value that changes linearly over a time"
  parameter Real height = 1 "Change over the ramp";
  parameter Real duration(unit = "s", min = 0) = 1 "How long the ramp lasts (0: a step)";
  parameter Real offset = 0 "Value before the ramp";
  parameter Real startTime(unit = "s") = 0 "When the ramp starts";
  Modelica.Blocks.Interfaces.RealOutput y "Value"
    annotation(Placement(transformation(extent = {{100, -10}, {120, 10}}), iconTransformation(extent = {{100, -10}, {120, 10}})));
equation
  y = offset + (if time < startTime then 0 elseif time < startTime + duration then (time - startTime) * height / duration else height);
  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "Ramp", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>A value that changes linearly over a time, as a setpoint ramped by the operator.</p><h4>How to read it</h4><p>The output is offset until startTime, then rises by height over duration and stays there; duration 0 makes it a step.</p><h4>Formula</h4><pre>y = offset + height·min(1, max(0, (t − startTime)/duration))</pre></html>"));
end Ramp;
