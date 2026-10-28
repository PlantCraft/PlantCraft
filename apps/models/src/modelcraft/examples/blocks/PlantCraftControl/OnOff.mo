within PlantCraftControl;
block OnOff "On/off: a controller with a hysteresis band"
  parameter Real bandwidth(min = 0) = 0.1 "Width of the band around the setpoint";
  parameter Real onValue = 1 "Output when on";
  parameter Real offValue = 0 "Output when off";
  parameter Boolean reverse = false "Reverse acting (on above the band, as for cooling)";
  Modelica.Blocks.Interfaces.RealInput sp "Setpoint"
    annotation(Placement(transformation(extent = {{-140, 40}, {-100, 80}}), iconTransformation(extent = {{-140, 40}, {-100, 80}})));
  Modelica.Blocks.Interfaces.RealInput pv "Measurement"
    annotation(Placement(transformation(extent = {{-140, -80}, {-100, -40}}), iconTransformation(extent = {{-140, -80}, {-100, -40}})));
  Modelica.Blocks.Interfaces.RealOutput op "Output"
    annotation(Placement(transformation(extent = {{100, -10}, {120, 10}}), iconTransformation(extent = {{100, -10}, {120, 10}})));
protected
  Boolean on(start = false, fixed = true) "Whether the output is on";
equation
  when (if reverse then pv > sp + bandwidth / 2 else pv < sp - bandwidth / 2) then
    on = true;
  elsewhen (if reverse then pv < sp - bandwidth / 2 else pv > sp + bandwidth / 2) then
    on = false;
  end when;
  op = if on then onValue else offValue;
  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "on/off", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>A controller that switches its output between two values, with a band around the setpoint so it does not chatter, as a thermostat.</p><h4>How to read it</h4><p>Direct acting: on when the measurement falls half a band below the setpoint, off when it rises half a band above it (the other way round when reverse acting). The wider the band, the fewer switches and the larger the swing.</p><h4>Formula</h4><pre>on when pv &lt; sp − band/2, off when pv &gt; sp + band/2 (reverse: the other way); op = onValue if on else offValue</pre></html>"));
end OnOff;
