within PlantCraftExamples;
model TankLevelControl "Tank level control: a PID holds the level of a tank by the speed of its feed pump"
  PlantCraftSources.Step setpoint(height=0.5, offset=1, startTime=600) "Level setpoint" annotation(Placement(transformation(extent={{-10,-10},{10,10}})));
  PlantCraftControl.PID controller(k=4, y_start=0.25) "Level controller" annotation(Placement(transformation(extent={{102,-20},{122,0}})));
  PlantCraftEquipment.Pump pump "Feed pump" annotation(Placement(transformation(extent={{214,-20},{234,0}})));
  PlantCraftSources.Step outlet(height=0.2, offset=0.5, startTime=1800) "Outlet valve opening" annotation(Placement(transformation(extent={{214,-90},{234,-70}})));
  PlantCraftEquipment.Tank tank "Tank" annotation(Placement(transformation(extent={{326,-30},{346,-10}})));
  PlantCraftEquipment.SensorLag sensor(T=2) "Level transmitter" annotation(Placement(transformation(extent={{438,-30},{458,-10}})));
  PlantCraftSinks.Scope2 level_scope "Level and setpoint" annotation(Placement(transformation(extent={{550,-10},{570,10}})));
  PlantCraftSinks.Scope speed_scope "Pump speed" annotation(Placement(transformation(extent={{326,40},{346,60}})));
equation
  connect(controller.op, pump.speed) annotation(Line(points={{126,-10},{210,-10}}, color={0,0,127}));
  connect(controller.op, speed_scope.u) annotation(Line(points={{126,-10},{322,50}}, color={0,0,127}));
  connect(outlet.y, tank.opening) annotation(Line(points={{238,-80},{322,-20}}, color={0,0,127}));
  connect(pump.q, tank.qIn) annotation(Line(points={{238,-10},{322,-20}}, color={0,0,127}));
  connect(sensor.y, controller.pv) annotation(Line(points={{462,-20},{98,-10}}, color={0,0,127}));
  connect(sensor.y, level_scope.u2) annotation(Line(points={{462,-20},{546,0}}, color={0,0,127}));
  connect(setpoint.y, controller.sp) annotation(Line(points={{14,0},{98,-10}}, color={0,0,127}));
  connect(setpoint.y, level_scope.u1) annotation(Line(points={{14,0},{546,0}}, color={0,0,127}));
  connect(tank.level, sensor.u) annotation(Line(points={{350,-20},{434,-20}}, color={0,0,127}));
  annotation(experiment(StartTime=0, StopTime=3600, Interval=1, Tolerance=1e-06), __OpenModelica_simulationFlags(s="dassl"));
end TankLevelControl;
