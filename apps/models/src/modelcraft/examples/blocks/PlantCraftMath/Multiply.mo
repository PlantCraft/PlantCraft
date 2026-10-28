within PlantCraftMath;
block Multiply "Product: two inputs multiplied"
  Modelica.Blocks.Interfaces.RealInput u1 "First input"
    annotation(Placement(transformation(extent = {{-140, 40}, {-100, 80}}), iconTransformation(extent = {{-140, 40}, {-100, 80}})));
  Modelica.Blocks.Interfaces.RealInput u2 "Second input"
    annotation(Placement(transformation(extent = {{-140, -80}, {-100, -40}}), iconTransformation(extent = {{-140, -80}, {-100, -40}})));
  Modelica.Blocks.Interfaces.RealOutput y "Product"
    annotation(Placement(transformation(extent = {{100, -10}, {120, 10}}), iconTransformation(extent = {{100, -10}, {120, 10}})));
equation
  y = u1 * u2;
  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "×", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>Two inputs multiplied, as a flow times a concentration gives a mass flow.</p><h4>How to read it</h4><p>The output is the product at each instant; it has no dynamics.</p><h4>Formula</h4><pre>y = u1·u2</pre></html>"));
end Multiply;
