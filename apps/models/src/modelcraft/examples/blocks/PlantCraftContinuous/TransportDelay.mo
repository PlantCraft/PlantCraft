within PlantCraftContinuous;
block TransportDelay "Dead time: the input as it was some time ago"
  parameter Real delayTime(unit = "s", min = 0) = 10 "Dead time";
  Modelica.Blocks.Interfaces.RealInput u "Input"
    annotation(Placement(transformation(extent = {{-140, -20}, {-100, 20}}), iconTransformation(extent = {{-140, -20}, {-100, 20}})));
  Modelica.Blocks.Interfaces.RealOutput y "Delayed input"
    annotation(Placement(transformation(extent = {{100, -10}, {120, 10}}), iconTransformation(extent = {{100, -10}, {120, 10}})));
equation
  y = delay(u, delayTime);
  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "e^-sT", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>Dead time: the input exactly as it was some seconds ago, as material that takes time to travel along a pipe or a belt.</p><h4>How to read it</h4><p>The output repeats the input shifted by delayTime. Before delayTime has passed it gives the input's first value.</p><h4>Formula</h4><pre>y(t) = u(t − delayTime)</pre></html>"));
end TransportDelay;
