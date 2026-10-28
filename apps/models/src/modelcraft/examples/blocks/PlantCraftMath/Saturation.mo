within PlantCraftMath;
block Saturation "Limits: the input kept between a lowest and a highest value"
  parameter Real uMax = 1 "Highest value";
  parameter Real uMin = 0 "Lowest value";
  Modelica.Blocks.Interfaces.RealInput u "Input"
    annotation(Placement(transformation(extent = {{-140, -20}, {-100, 20}}), iconTransformation(extent = {{-140, -20}, {-100, 20}})));
  Modelica.Blocks.Interfaces.RealOutput y "Limited value"
    annotation(Placement(transformation(extent = {{100, -10}, {120, 10}}), iconTransformation(extent = {{100, -10}, {120, 10}})));
equation
  y = max(uMin, min(uMax, u));
  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "Saturation", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>The input kept between a lowest and a highest value, as a valve that cannot open past 0..100 %.</p><h4>How to read it</h4><p>The output equals the input inside the limits and sticks to uMin or uMax outside them.</p><h4>Formula</h4><pre>y = max(uMin, min(uMax, u))</pre></html>"));
end Saturation;
