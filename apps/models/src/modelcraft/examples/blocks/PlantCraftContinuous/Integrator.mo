within PlantCraftContinuous;
block Integrator "Integrator: the integral of the input over time"
  parameter Real k = 1 "Gain";
  parameter Real y_start = 0 "Output when the simulation starts";
  Modelica.Blocks.Interfaces.RealInput u "Input"
    annotation(Placement(transformation(extent = {{-140, -20}, {-100, 20}}), iconTransformation(extent = {{-140, -20}, {-100, 20}})));
  Modelica.Blocks.Interfaces.RealOutput y(start = y_start, fixed = true) "Integral"
    annotation(Placement(transformation(extent = {{100, -10}, {120, 10}}), iconTransformation(extent = {{100, -10}, {120, 10}})));
equation
  der(y) = k * u;
  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "1/s", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>The integral of the input over time, as a volume is the integral of a flow.</p><h4>How to read it</h4><p>The output keeps growing while the input is positive and falls while it is negative; it stays still only when the input is zero. It starts at y_start.</p><h4>Formula</h4><pre>dy/dt = k·u,  y(0) = y_start</pre></html>"));
end Integrator;
