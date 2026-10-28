within PlantCraftControl;
block PID "PID: a controller with output limits and anti-windup"
  parameter Real k = 1 "Proportional gain";
  parameter Real Ti(unit = "s", min = 1e-6) = 60 "Integral time";
  parameter Real Td(unit = "s", min = 0) = 0 "Derivative time (0: a PI controller)";
  parameter Real yMax = 1 "Highest output";
  parameter Real yMin = 0 "Lowest output";
  parameter Real y_start = 0.5 "Output when the simulation starts";
  parameter Boolean reverse = false "Reverse acting (the output falls when the measurement rises above the setpoint)";
  Modelica.Blocks.Interfaces.RealInput sp "Setpoint"
    annotation(Placement(transformation(extent = {{-140, 40}, {-100, 80}}), iconTransformation(extent = {{-140, 40}, {-100, 80}})));
  Modelica.Blocks.Interfaces.RealInput pv "Measurement"
    annotation(Placement(transformation(extent = {{-140, -80}, {-100, -40}}), iconTransformation(extent = {{-140, -80}, {-100, -40}})));
  Modelica.Blocks.Interfaces.RealOutput op "Output"
    annotation(Placement(transformation(extent = {{100, -10}, {120, 10}}), iconTransformation(extent = {{100, -10}, {120, 10}})));
protected
  Modelica.Blocks.Continuous.LimPID pid(controllerType = if Td > 0 then Modelica.Blocks.Types.SimpleController.PID else Modelica.Blocks.Types.SimpleController.PI, k = if reverse then -k else k, Ti = Ti, Td = max(Td, 1e-6), yMax = yMax, yMin = yMin, initType = Modelica.Blocks.Types.Init.InitialOutput, y_start = y_start);
equation
  connect(sp, pid.u_s);
  connect(pv, pid.u_m);
  connect(pid.y, op);
  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "PID", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>The plant's usual controller: proportional, integral and derivative action on the error between setpoint and measurement, with output limits and anti-windup (the Modelica Standard Library's LimPID).</p><h4>How to read it</h4><p>k sets how strongly it reacts, Ti how fast it removes a lasting error (smaller is faster), Td adds anticipation (0 makes it a PI). Reverse acting makes the output fall when the measurement rises above the setpoint. The output starts at y_start and stays between yMin and yMax.</p><h4>Formula</h4><pre>op = k·(e + (1/Ti)·∫e dt + Td·de/dt),  e = sp − pv (reverse: pv − sp),  limited to yMin..yMax</pre></html>"));
end PID;
