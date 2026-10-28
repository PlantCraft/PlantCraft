within PlantCraftExamples;
model FirstOrderDeadTimeLoop "First order plus dead time loop: a PI controller on a lagged, delayed process"
  PlantCraftSources.Step setpoint(startTime=10) "Setpoint" annotation(Placement(transformation(extent={{-10,-10},{10,10}})));
  PlantCraftControl.PID controller(Ti=25, k=1.2, yMax=5, yMin=-5, y_start=0) "Controller" annotation(Placement(transformation(extent={{102,-20},{122,0}})));
  PlantCraftContinuous.FirstOrder process(T=20, k=2) "Process lag" annotation(Placement(transformation(extent={{214,-20},{234,0}})));
  PlantCraftContinuous.TransportDelay dead_time(delayTime=5) "Dead time" annotation(Placement(transformation(extent={{326,-20},{346,0}})));
  PlantCraftSinks.Scope2 scope "Output and setpoint" annotation(Placement(transformation(extent={{438,-10},{458,10}})));
equation
  connect(controller.op, process.u) annotation(Line(points={{126,-10},{210,-10}}, color={0,0,127}));
  connect(dead_time.y, controller.pv) annotation(Line(points={{350,-10},{98,-10}}, color={0,0,127}));
  connect(dead_time.y, scope.u2) annotation(Line(points={{350,-10},{434,0}}, color={0,0,127}));
  connect(process.y, dead_time.u) annotation(Line(points={{238,-10},{322,-10}}, color={0,0,127}));
  connect(setpoint.y, controller.sp) annotation(Line(points={{14,0},{98,-10}}, color={0,0,127}));
  connect(setpoint.y, scope.u1) annotation(Line(points={{14,0},{434,0}}, color={0,0,127}));
  annotation(experiment(StartTime=0, StopTime=300, Interval=0.1, Tolerance=1e-06), __OpenModelica_simulationFlags(s="dassl"));
end FirstOrderDeadTimeLoop;
