within PlantCraftSinks;
block Scope2 "Scope (2 signals): two signals on one chart"
  Modelica.Blocks.Interfaces.RealInput u1 "First signal"
    annotation(Placement(transformation(extent = {{-140, 40}, {-100, 80}}), iconTransformation(extent = {{-140, 40}, {-100, 80}})));
  Modelica.Blocks.Interfaces.RealInput u2 "Second signal"
    annotation(Placement(transformation(extent = {{-140, -80}, {-100, -40}}), iconTransformation(extent = {{-140, -80}, {-100, -40}})));

  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "scope", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>Shows two signals on one chart of the results, as a setpoint and its measurement or an inlet and an outlet.</p><h4>How to read it</h4><p>Wire to it the two signals you want to compare; it changes nothing in the model.</p></html>"));
end Scope2;
