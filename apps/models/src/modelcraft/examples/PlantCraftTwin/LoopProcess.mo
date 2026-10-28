within PlantCraftTwin;
model LoopProcess "One control loop's process: first order plus dead time, with a measured disturbance"
  parameter Real K = 0.55 "Process gain (PV units per % of valve)";
  parameter Real tau(unit = "s", min = 1e-3) = 150 "Time constant";
  parameter Real theta(unit = "s", min = 0) = 15 "Dead time";
  parameter Real thetaMax(unit = "s") = 600 "Longest dead time the delay line holds";
  parameter Real u0 = 50 "Valve position at the operating point (%)";
  parameter Real y0 = 50 "PV at the operating point";
  parameter Real Kd = 0 "Gain of the measured disturbance";
  parameter Real d0 = 50 "Disturbance at the operating point";
  parameter Real y_start = 50 "PV when the simulation starts (TwinCraft sets it from the measurement)";
  input Real u(start = 50) "Valve position (%)";
  input Real d(start = 50) "Measured disturbance";
  output Real y(start = y_start, fixed = true) "Predicted PV";
equation
  tau * der(y) = y0 + K * (delay(u, theta, thetaMax) - u0) + Kd * (d - d0) - y;
  annotation(experiment(StartTime = 0, StopTime = 3600, Interval = 5));
end LoopProcess;
