within PlantCraftMath;
block RateLimiter "Rate limiter: the output follows the input no faster than a rate"
  parameter Real Rising(min = 0) = 1 "Fastest rise (per second)";
  parameter Real Falling(max = 0) = -1 "Fastest fall (per second, negative)";
  parameter Real Td(unit = "s", min = 1e-9) = 0.001 "Time constant with which it follows when not limited";
  Modelica.Blocks.Interfaces.RealInput u "Input"
    annotation(Placement(transformation(extent = {{-140, -20}, {-100, 20}}), iconTransformation(extent = {{-140, -20}, {-100, 20}})));
  Modelica.Blocks.Interfaces.RealOutput y "Output"
    annotation(Placement(transformation(extent = {{100, -10}, {120, 10}}), iconTransformation(extent = {{100, -10}, {120, 10}})));
initial equation
  y = u;
equation
  der(y) = max(Falling, min(Rising, (u - y) / Td));
  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "rate", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>The output follows the input, but never faster than a rise and a fall rate, as an operator ramping a setpoint.</p><h4>How to read it</h4><p>When the input jumps, the output ramps at Rising (or Falling) per second until it catches up; small changes pass almost unchanged.</p><h4>Formula</h4><pre>dy/dt = (u − y)/Td, kept between Falling and Rising</pre></html>"));
end RateLimiter;
