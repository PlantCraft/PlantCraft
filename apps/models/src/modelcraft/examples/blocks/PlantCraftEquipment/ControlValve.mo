within PlantCraftEquipment;
block ControlValve "Control valve: flow from the opening and the pressure drop"
  parameter Real Cv(unit = "m3/(s.bar0.5)") = 0.01 "Flow coefficient at full opening";
  parameter Real R(min = 1) = 30 "Rangeability (equal percentage characteristic)";
  parameter Boolean equalPercentage = false "Equal percentage characteristic (else linear)";
  Modelica.Blocks.Interfaces.RealInput opening(min = 0, max = 1) "Opening (0 to 1)"
    annotation(Placement(transformation(extent = {{-140, 40}, {-100, 80}}), iconTransformation(extent = {{-140, 40}, {-100, 80}})));
  Modelica.Blocks.Interfaces.RealInput dp(unit = "bar") "Pressure drop across the valve"
    annotation(Placement(transformation(extent = {{-140, -80}, {-100, -40}}), iconTransformation(extent = {{-140, -80}, {-100, -40}})));
  Modelica.Blocks.Interfaces.RealOutput q(unit = "m3/s") "Flow through the valve"
    annotation(Placement(transformation(extent = {{100, -10}, {120, 10}}), iconTransformation(extent = {{100, -10}, {120, 10}})));
protected
  Real f "Characteristic: fraction of Cv at this opening";
equation
  f = if equalPercentage then R ^ (max(0, min(1, opening)) - 1) else max(0, min(1, opening));
  q = Cv * f * sqrt(max(dp, 0));
  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "valve", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>The flow through a control valve from its opening and the pressure drop, with a linear or an equal-percentage characteristic.</p><h4>How to read it</h4><p>At full opening the flow is Cv·√Δp. With the equal-percentage characteristic the flow grows slowly at small openings and fast near the top. The opening is clipped to 0..1 and a negative pressure drop gives no flow.</p><h4>Formula</h4><pre>q = Cv·f(u)·√Δp,  f(u) = u (linear) or R^(u − 1) (equal percentage)</pre></html>"));
end ControlValve;
