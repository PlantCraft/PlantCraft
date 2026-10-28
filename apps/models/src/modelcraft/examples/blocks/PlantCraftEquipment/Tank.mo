within PlantCraftEquipment;
block Tank "Tank with an inflow and an outflow through a valve"
  parameter Real A(unit = "m2") = 2 "Cross-section";
  parameter Real Cv(unit = "m2.5/s") = 0.05 "Outlet valve coefficient at full opening";
  parameter Real h_start(unit = "m") = 1 "Level when the simulation starts";
  Modelica.Blocks.Interfaces.RealInput qIn(unit = "m3/s") "Inflow"
    annotation(Placement(transformation(extent = {{-140, 40}, {-100, 80}}), iconTransformation(extent = {{-140, 40}, {-100, 80}})));
  Modelica.Blocks.Interfaces.RealInput opening(min = 0, max = 1) "Outlet valve opening (0 to 1)"
    annotation(Placement(transformation(extent = {{-140, -80}, {-100, -40}}), iconTransformation(extent = {{-140, -80}, {-100, -40}})));
  Modelica.Blocks.Interfaces.RealOutput level(unit = "m", start = h_start, fixed = true) "Level"
    annotation(Placement(transformation(extent = {{100, 50}, {120, 70}}), iconTransformation(extent = {{100, 50}, {120, 70}})));
  Modelica.Blocks.Interfaces.RealOutput qOut(unit = "m3/s") "Outflow"
    annotation(Placement(transformation(extent = {{100, -70}, {120, -50}}), iconTransformation(extent = {{100, -70}, {120, -50}})));
equation
  qOut = Cv * max(0, min(1, opening)) * sqrt(max(level, 0));
  A * der(level) = qIn - qOut;
  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "tank", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>A tank filled by an inflow and emptied by gravity through an outlet valve.</p><h4>How to read it</h4><p>The level rises while the inflow is larger than the outflow. The outflow grows with the square root of the level, so the tank finds a level where both are equal; a larger A makes it slower.</p><h4>Formula</h4><pre>A·dh/dt = qIn − qOut,  qOut = Cv·u·√h</pre></html>"));
end Tank;
