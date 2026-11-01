within PlantCraftProcess;
model MethanolWaterFlash "Flash drum: a methanol and water feed split into vapour and liquid at 1 atm, the feed heated over ten minutes"
  // Components, thermodynamics and the flash from OMChemSim (the Simulator package,
  // BSD-3-Clause), which the runner loads; this model is PlantCraft's own.
  import data = Simulator.Files.ChemsepDatabase;
  parameter data.Methanol methanol;
  parameter data.Water water;
  parameter Integer Nc = 2 "Number of components";
  parameter data.GeneralProperties C[Nc] = {methanol, water};
  parameter Real feed_flow(unit = "mol/s") = 100 "Feed flow";
  parameter Real feed_methanol(unit = "1") = 0.4 "Methanol mole fraction in the feed";
  parameter Real T_start(unit = "K") = 355 "Feed temperature at the start";
  parameter Real T_end(unit = "K") = 362 "Feed temperature after the ramp";
  parameter Real ramp_time(unit = "s") = 600 "Time the feed takes to heat";
  PlantCraftProcess.Stream feed(Nc = Nc, C = C) "Feed" annotation(Placement(transformation(extent = {{-90, -10}, {-70, 10}})));
  PlantCraftProcess.FlashDrum drum(Nc = Nc, C = C) "Flash drum" annotation(Placement(transformation(extent = {{-10, -10}, {10, 10}})));
  PlantCraftProcess.Stream vapour(Nc = Nc, C = C) "Vapour" annotation(Placement(transformation(extent = {{70, 20}, {90, 40}})));
  PlantCraftProcess.Stream liquid(Nc = Nc, C = C) "Liquid" annotation(Placement(transformation(extent = {{70, -40}, {90, -20}})));
equation
  connect(feed.Out, drum.In) annotation(Line(points = {{-70, 0}, {-10, 0}}, color = {0, 70, 70}));
  connect(drum.Out1, vapour.In) annotation(Line(points = {{10, 8}, {70, 30}}, color = {0, 70, 70}));
  connect(drum.Out2, liquid.In) annotation(Line(points = {{10, -8}, {70, -30}}, color = {0, 70, 70}));
  feed.P = 101325;
  feed.T = T_start + (T_end - T_start) * min(time / ramp_time, 1);
  feed.F_p[1] = feed_flow;
  feed.x_pc[1, :] = {feed_methanol, 1 - feed_methanol};
  annotation(experiment(StartTime = 0, StopTime = 900, Interval = 10, Tolerance = 1e-06), __OpenModelica_simulationFlags(s = "dassl"));
end MethanolWaterFlash;
