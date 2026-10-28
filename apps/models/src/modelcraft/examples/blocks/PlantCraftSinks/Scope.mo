within PlantCraftSinks;
block Scope "Scope: a signal shown in the results"
  Modelica.Blocks.Interfaces.RealInput u "Signal shown"
    annotation(Placement(transformation(extent = {{-140, -20}, {-100, 20}}), iconTransformation(extent = {{-140, -20}, {-100, 20}})));

  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "scope", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>Shows a signal in the simulation's results and in the indicators a study compares.</p><h4>How to read it</h4><p>Wire to it what you want to see on the chart; it changes nothing in the model.</p></html>"));
end Scope;
