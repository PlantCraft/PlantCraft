within PlantCraftMath;
block Gain "Gain: the input times a factor"
  parameter Real k = 1 "Factor";
  Modelica.Blocks.Interfaces.RealInput u "Input"
    annotation(Placement(transformation(extent = {{-140, -20}, {-100, 20}}), iconTransformation(extent = {{-140, -20}, {-100, 20}})));
  Modelica.Blocks.Interfaces.RealOutput y "Output"
    annotation(Placement(transformation(extent = {{100, -10}, {120, 10}}), iconTransformation(extent = {{100, -10}, {120, 10}})));
equation
  y = k * u;
  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "k", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>The input times a factor: a unit conversion, a scale or a sign change.</p><h4>How to read it</h4><p>The output is k times the input at each instant; it has no dynamics.</p><h4>Formula</h4><pre>y = k·u</pre></html>"));
end Gain;
