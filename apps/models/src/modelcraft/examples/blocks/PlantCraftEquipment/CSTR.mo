within PlantCraftEquipment;
block CSTR "Cooled exothermic stirred-tank reactor (A to B, first order)"
  parameter Real V(unit = "m3") = 1 "Volume";
  parameter Real CA_in(unit = "mol/m3") = 1000 "Feed concentration";
  parameter Real T_in(unit = "K") = 350 "Feed temperature";
  parameter Real k0(unit = "1/s") = 1.2e9 "Pre-exponential factor";
  parameter Real EoverR(unit = "K") = 8750 "Activation energy over the gas constant";
  parameter Real dH(unit = "J/mol") = -5e4 "Heat of reaction";
  parameter Real rho_cp(unit = "J/(m3.K)") = 239000 "Density times specific heat";
  parameter Real UA(unit = "W/K") = 833.3 "Heat transfer to the jacket";
  parameter Real CA_start(unit = "mol/m3") = 500 "Concentration when the simulation starts";
  parameter Real T_start(unit = "K") = 350 "Temperature when the simulation starts";
  Modelica.Blocks.Interfaces.RealInput q(unit = "m3/s") "Feed flow"
    annotation(Placement(transformation(extent = {{-140, 40}, {-100, 80}}), iconTransformation(extent = {{-140, 40}, {-100, 80}})));
  Modelica.Blocks.Interfaces.RealInput Tc(unit = "K") "Jacket temperature"
    annotation(Placement(transformation(extent = {{-140, -80}, {-100, -40}}), iconTransformation(extent = {{-140, -80}, {-100, -40}})));
  Modelica.Blocks.Interfaces.RealOutput CA(unit = "mol/m3", start = CA_start, fixed = true) "Concentration of A"
    annotation(Placement(transformation(extent = {{100, 50}, {120, 70}}), iconTransformation(extent = {{100, 50}, {120, 70}})));
  Modelica.Blocks.Interfaces.RealOutput T(unit = "K", start = T_start, fixed = true) "Reactor temperature"
    annotation(Placement(transformation(extent = {{100, -70}, {120, -50}}), iconTransformation(extent = {{100, -70}, {120, -50}})));
protected
  Real r(unit = "mol/(m3.s)") "Reaction rate";
equation
  r = k0 * exp(-EoverR / T) * CA;
  V * der(CA) = q * (CA_in - CA) - V * r;
  V * rho_cp * der(T) = q * rho_cp * (T_in - T) - dH * V * r + UA * (Tc - T);
  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "CSTR", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>A cooled stirred-tank reactor with one exothermic first-order reaction A → B: the textbook model of reactor temperature and conversion.</p><h4>How to read it</h4><p>CA falls when the reaction runs faster (higher temperature); T rises with the heat of reaction and falls with the jacket's cooling. A small change in Tc can make the reactor run away: watch T after a step.</p><h4>Formula</h4><pre>r = k0·exp(−E/R / T)·CA<br/>V·dCA/dt = q·(CA_in − CA) − V·r<br/>V·ρcp·dT/dt = q·ρcp·(T_in − T) − ΔH·V·r + UA·(Tc − T)</pre></html>"));
end CSTR;
