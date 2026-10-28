within PlantCraftEquipment;
block SensorLag "Sensor: a measurement with a lag and an offset"
  parameter Real T(unit = "s", min = 1e-9) = 1 "Time constant of the sensor";
  parameter Real offset = 0 "Constant measurement error";
  Modelica.Blocks.Interfaces.RealInput u "True value"
    annotation(Placement(transformation(extent = {{-140, -20}, {-100, 20}}), iconTransformation(extent = {{-140, -20}, {-100, 20}})));
  Modelica.Blocks.Interfaces.RealOutput y "Measured value"
    annotation(Placement(transformation(extent = {{100, -10}, {120, 10}}), iconTransformation(extent = {{100, -10}, {120, 10}})));
protected
  Real x "Lagged value";
initial equation
  x = u;
equation
  T * der(x) = u - x;
  y = x + offset;
  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "sensor", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>What an instrument reports: the true value seen through a time constant, plus a constant error.</p><h4>How to read it</h4><p>The measured value lags the true one by about T seconds and is offset by offset. Compare the two to see how much a slow or biased sensor hides. It starts reading the true value.</p><h4>Formula</h4><pre>T·dx/dt = u − x,  y = x + offset</pre></html>"));
end SensorLag;
