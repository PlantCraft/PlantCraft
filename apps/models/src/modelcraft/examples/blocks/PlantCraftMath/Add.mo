within PlantCraftMath;
block Add "Sum: two inputs added, each with its own sign or weight"
  parameter Real k1 = 1 "Weight of u1 (+1 adds it, -1 subtracts it)";
  parameter Real k2 = 1 "Weight of u2 (+1 adds it, -1 subtracts it)";
  Modelica.Blocks.Interfaces.RealInput u1 "First input"
    annotation(Placement(transformation(extent = {{-140, 40}, {-100, 80}}), iconTransformation(extent = {{-140, 40}, {-100, 80}})));
  Modelica.Blocks.Interfaces.RealInput u2 "Second input"
    annotation(Placement(transformation(extent = {{-140, -80}, {-100, -40}}), iconTransformation(extent = {{-140, -80}, {-100, -40}})));
  Modelica.Blocks.Interfaces.RealOutput y "Sum"
    annotation(Placement(transformation(extent = {{100, -10}, {120, 10}}), iconTransformation(extent = {{100, -10}, {120, 10}})));
equation
  y = k1 * u1 + k2 * u2;
  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "+", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>Two inputs added, each with its own weight: with k2 = −1 it gives a difference, as the error between a setpoint and a measurement.</p><h4>How to read it</h4><p>The output is the weighted sum at each instant; it has no dynamics.</p><h4>Formula</h4><pre>y = k1·u1 + k2·u2</pre></html>"));
end Add;
