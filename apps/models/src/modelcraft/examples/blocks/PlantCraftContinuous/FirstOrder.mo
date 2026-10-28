within PlantCraftContinuous;
block FirstOrder "First order: a lag with a gain and a time constant"
  parameter Real k = 1 "Gain";
  parameter Real T(unit = "s", min = 1e-9) = 60 "Time constant";
  parameter Boolean steady_start = true "Start in steady state (else from the initial value)";
  parameter Real y_start = 0 "Output when the simulation starts (if not in steady state)";
  Modelica.Blocks.Interfaces.RealInput u "Input"
    annotation(Placement(transformation(extent = {{-140, -20}, {-100, 20}}), iconTransformation(extent = {{-140, -20}, {-100, 20}})));
  Modelica.Blocks.Interfaces.RealOutput y "Output"
    annotation(Placement(transformation(extent = {{100, -10}, {120, 10}}), iconTransformation(extent = {{100, -10}, {120, 10}})));
initial equation
  if steady_start then
    der(y) = 0;
  else
    y = y_start;
  end if;
equation
  T * der(y) = k * u - y;
  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "k/(Ts+1)", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>A lag: the output moves towards k times the input and gets 63 % of the way there in T seconds. The usual model of a sensor, a small tank or any slow response.</p><h4>How to read it</h4><p>After a step of the input, the output reaches 63 % of its change in T, 95 % in 3·T and stays at k times the input. By default it starts in steady state (y = k·u).</p><h4>Formula</h4><pre>T·dy/dt = k·u − y   (transfer function k/(T·s + 1))</pre></html>"));
end FirstOrder;
