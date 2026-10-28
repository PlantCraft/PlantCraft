within PlantCraftSources;
block Step "Step: a value that jumps at a given time"
  parameter Real height = 1 "Size of the step";
  parameter Real offset = 0 "Value before the step";
  parameter Real startTime(unit = "s") = 0 "When the step happens";
  Modelica.Blocks.Interfaces.RealOutput y "Value"
    annotation(Placement(transformation(extent = {{100, -10}, {120, 10}}), iconTransformation(extent = {{100, -10}, {120, 10}})));
equation
  y = offset + (if time < startTime then 0 else height);
  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "Step", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>A value that jumps at a given time: the usual test of how a model or a loop responds.</p><h4>How to read it</h4><p>The output is offset before startTime and offset + height after it.</p><h4>Formula</h4><pre>y = offset + (height if t ≥ startTime else 0)</pre></html>"));
end Step;
