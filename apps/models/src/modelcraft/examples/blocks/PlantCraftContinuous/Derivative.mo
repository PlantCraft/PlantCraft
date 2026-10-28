within PlantCraftContinuous;
block Derivative "Derivative: how fast the input changes, filtered"
  parameter Real k = 1 "Gain";
  parameter Real T(unit = "s", min = 1e-9) = 0.01 "Filter time constant (small: closer to the exact derivative)";
  Modelica.Blocks.Interfaces.RealInput u "Input"
    annotation(Placement(transformation(extent = {{-140, -20}, {-100, 20}}), iconTransformation(extent = {{-140, -20}, {-100, 20}})));
  Modelica.Blocks.Interfaces.RealOutput y "Rate of change"
    annotation(Placement(transformation(extent = {{100, -10}, {120, 10}}), iconTransformation(extent = {{100, -10}, {120, 10}})));
protected
  Real x "Filtered input";
initial equation
  x = u;
equation
  der(x) = (u - x) / T;
  y = k * (u - x) / T;
  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "du/dt", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>How fast the input changes, per second, with a small filter so a step does not give an infinite spike.</p><h4>How to read it</h4><p>A positive output means the input is rising, a negative one that it is falling; the larger T, the smoother and later the answer.</p><h4>Formula</h4><pre>y = k·s/(T·s + 1)·u, that is dx/dt = (u − x)/T and y = k·(u − x)/T</pre></html>"));
end Derivative;
