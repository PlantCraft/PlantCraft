within PlantCraftEquipment;
block Pump "Pump with a speed command: flow proportional to speed"
  parameter Real qMax(unit = "m3/s") = 0.1 "Flow at full speed";
  parameter Real tau(unit = "s", min = 1e-6) = 2 "Time constant of the speed change";
  parameter Boolean steady_start = true "Start in steady state (else from the initial value)";
  Modelica.Blocks.Interfaces.RealInput speed(min = 0, max = 1) "Speed command (0 to 1)"
    annotation(Placement(transformation(extent = {{-140, -20}, {-100, 20}}), iconTransformation(extent = {{-140, -20}, {-100, 20}})));
  Modelica.Blocks.Interfaces.RealOutput q(unit = "m3/s") "Delivered flow"
    annotation(Placement(transformation(extent = {{100, -10}, {120, 10}}), iconTransformation(extent = {{100, -10}, {120, 10}})));
initial equation
  if steady_start then
    q = qMax * max(0, min(1, speed));
  else
    q = 0;
  end if;
equation
  tau * der(q) = qMax * max(0, min(1, speed)) - q;
  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "pump", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>A pump driven by a speed command: the flow follows the speed with a short lag.</p><h4>How to read it</h4><p>At full speed it gives qMax; the flow reaches 63 % of a change in tau seconds. The speed is clipped to 0..1. By default it starts at the flow of its first speed, else from zero.</p><h4>Formula</h4><pre>tau·dq/dt = qMax·s − q,  s = speed clipped to 0..1</pre></html>"));
end Pump;
