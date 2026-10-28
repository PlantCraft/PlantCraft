within PlantCraftSources;
block ConstantValue "Constant: a value that does not change"
  parameter Real k = 1 "Value";
  Modelica.Blocks.Interfaces.RealOutput y "Value"
    annotation(Placement(transformation(extent = {{100, -10}, {120, 10}}), iconTransformation(extent = {{100, -10}, {120, 10}})));
equation
  y = k;
  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "k", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>A value that does not change: a setpoint, a feed temperature or a fixed opening.</p><h4>How to read it</h4><p>The output is k from start to end.</p><h4>Formula</h4><pre>y = k</pre></html>"));
end ConstantValue;
