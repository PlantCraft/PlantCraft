within PlantCraftTwin;
model Furnaces "PlantCraft's furnace area: two furnace outlet temperatures and the fuel gas flow"
  LoopProcess TIC1104(K = 0.55, tau = 320, theta = 15, y0 = 68, y_start = 68) "Furnace outlet temperature, pass A";
  LoopProcess TIC1209(K = 0.55, tau = 340, theta = 15, y0 = 69, y_start = 69) "Furnace outlet temperature, pass B";
  LoopProcess FIC1210(K = 0.55, tau = 150, theta = 15, y0 = 57, y_start = 57) "Fuel gas flow";
  input Real TIC1104_OP(start = 50) "TIC-1104 valve position (%)";
  input Real TIC1209_OP(start = 50) "TIC-1209 valve position (%)";
  input Real FIC1210_OP(start = 50) "FIC-1210 valve position (%)";
  output Real TIC1104_PV "TIC-1104 predicted temperature (degC)";
  output Real TIC1209_PV "TIC-1209 predicted temperature (degC)";
  output Real FIC1210_PV "FIC-1210 predicted flow (Nm3/h)";
equation
  TIC1104.u = TIC1104_OP;
  TIC1209.u = TIC1209_OP;
  FIC1210.u = FIC1210_OP;
  TIC1104.d = 50;
  TIC1209.d = 50;
  FIC1210.d = 50;
  TIC1104_PV = TIC1104.y;
  TIC1209_PV = TIC1209.y;
  FIC1210_PV = FIC1210.y;
  annotation(experiment(StartTime = 0, StopTime = 3600, Interval = 5));
end Furnaces;
