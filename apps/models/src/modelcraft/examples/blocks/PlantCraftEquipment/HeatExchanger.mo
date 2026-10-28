within PlantCraftEquipment;
block HeatExchanger "Counter-current heat exchanger in cells: hot water cooled by cold water"
  parameter Integer N(min = 1) = 10 "Number of cells";
  parameter Real U(unit = "W/(m2.K)") = 800 "Heat transfer coefficient";
  parameter Real A(unit = "m2") = 10 "Heat transfer area";
  parameter Real cp(unit = "J/(kg.K)") = 4180 "Specific heat of water";
  parameter Real Mh(unit = "kg") = 50 "Hot side hold-up";
  parameter Real Mc(unit = "kg") = 50 "Cold side hold-up";
  Modelica.Blocks.Interfaces.RealInput mh(unit = "kg/s") "Hot flow"
    annotation(Placement(transformation(extent = {{-140, 40}, {-100, 80}}), iconTransformation(extent = {{-140, 40}, {-100, 80}})));
  Modelica.Blocks.Interfaces.RealInput mc(unit = "kg/s") "Cold flow"
    annotation(Placement(transformation(extent = {{-140, 0}, {-100, 40}}), iconTransformation(extent = {{-140, 0}, {-100, 40}})));
  Modelica.Blocks.Interfaces.RealInput Th_in(unit = "degC") "Hot inlet temperature"
    annotation(Placement(transformation(extent = {{-140, -40}, {-100, 0}}), iconTransformation(extent = {{-140, -40}, {-100, 0}})));
  Modelica.Blocks.Interfaces.RealInput Tc_in(unit = "degC") "Cold inlet temperature"
    annotation(Placement(transformation(extent = {{-140, -80}, {-100, -40}}), iconTransformation(extent = {{-140, -80}, {-100, -40}})));
  Modelica.Blocks.Interfaces.RealOutput Th_out(unit = "degC") "Hot outlet temperature"
    annotation(Placement(transformation(extent = {{100, 50}, {120, 70}}), iconTransformation(extent = {{100, 50}, {120, 70}})));
  Modelica.Blocks.Interfaces.RealOutput Tc_out(unit = "degC") "Cold outlet temperature"
    annotation(Placement(transformation(extent = {{100, -10}, {120, 10}}), iconTransformation(extent = {{100, -10}, {120, 10}})));
  Modelica.Blocks.Interfaces.RealOutput duty(unit = "kW") "Heat duty"
    annotation(Placement(transformation(extent = {{100, -70}, {120, -50}}), iconTransformation(extent = {{100, -70}, {120, -50}})));
protected
  Real Th[N](each unit = "degC") "Hot side temperatures, inlet to outlet";
  Real Tc[N](each unit = "degC") "Cold side temperatures, its inlet at cell N";
  Real Q[N](each unit = "W") "Heat through each cell";
initial equation
  for i in 1:N loop
    der(Th[i]) = 0;
    der(Tc[i]) = 0;
  end for;
equation
  for i in 1:N loop
    Q[i] = U * A / N * (Th[i] - Tc[i]);
    Mh / N * cp * der(Th[i]) = mh * cp * ((if i == 1 then Th_in else Th[i - 1]) - Th[i]) - Q[i];
    Mc / N * cp * der(Tc[i]) = mc * cp * ((if i == N then Tc_in else Tc[i + 1]) - Tc[i]) + Q[i];
  end for;
  Th_out = Th[N];
  Tc_out = Tc[1];
  duty = sum(Q) / 1000;
  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "HX", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>A counter-current heat exchanger in which hot water is cooled by cold water, cut into N cells along its length.</p><h4>How to read it</h4><p>More area A or a higher U brings the outlets closer to the other side's inlet; a larger flow on one side makes its temperature change less. Th_out is never below Tc_in. It starts in steady state.</p><h4>Formula</h4><pre>in each cell i: Q = U·A/N·(Th,i − Tc,i);  Mh/N·cp·dTh,i/dt = mh·cp·(Th,i−1 − Th,i) − Q;  Mc/N·cp·dTc,i/dt = mc·cp·(Tc,i+1 − Tc,i) + Q</pre></html>"));
end HeatExchanger;
