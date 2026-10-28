within PlantCraftExamples;
model HeatExchangerOutlet "Heat exchanger outlet: hot water cooled by cold water, with a step in the hot flow"
  PlantCraftSources.Step hot_flow(height=0.5, offset=2, startTime=300) "Hot flow" annotation(Placement(transformation(extent={{-10,-10},{10,10}})));
  PlantCraftSources.ConstantValue cold_flow(k=3) "Cold flow" annotation(Placement(transformation(extent={{-10,-50},{10,-30}})));
  PlantCraftSources.ConstantValue hot_inlet(k=90) "Hot inlet temperature" annotation(Placement(transformation(extent={{-10,-90},{10,-70}})));
  PlantCraftSources.ConstantValue cold_inlet(k=25) "Cold inlet temperature" annotation(Placement(transformation(extent={{-10,-130},{10,-110}})));
  PlantCraftEquipment.HeatExchanger exchanger "Heat exchanger" annotation(Placement(transformation(extent={{130,-60},{150,-40}})));
  PlantCraftSinks.Scope2 outlet_scope "Outlet temperatures" annotation(Placement(transformation(extent={{270,-30},{290,-10}})));
  PlantCraftSinks.Scope duty_scope "Heat duty" annotation(Placement(transformation(extent={{270,-110},{290,-90}})));
equation
  connect(cold_flow.y, exchanger.mc) annotation(Line(points={{14,-40},{126,-50}}, color={0,0,127}));
  connect(cold_inlet.y, exchanger.Tc_in) annotation(Line(points={{14,-120},{126,-50}}, color={0,0,127}));
  connect(exchanger.Tc_out, outlet_scope.u2) annotation(Line(points={{154,-50},{266,-20}}, color={0,0,127}));
  connect(exchanger.Th_out, outlet_scope.u1) annotation(Line(points={{154,-50},{266,-20}}, color={0,0,127}));
  connect(exchanger.duty, duty_scope.u) annotation(Line(points={{154,-50},{266,-100}}, color={0,0,127}));
  connect(hot_flow.y, exchanger.mh) annotation(Line(points={{14,0},{126,-50}}, color={0,0,127}));
  connect(hot_inlet.y, exchanger.Th_in) annotation(Line(points={{14,-80},{126,-50}}, color={0,0,127}));
  annotation(experiment(StartTime=0, StopTime=1200, Interval=1, Tolerance=1e-06), __OpenModelica_simulationFlags(s="dassl"));
end HeatExchangerOutlet;
