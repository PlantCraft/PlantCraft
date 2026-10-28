within PlantCraftContinuous;
block TransferFunction "Transfer function: numerator and denominator in s"
  parameter Real b[:] = {1} "Numerator coefficients, highest power of s first";
  parameter Real a[:] = {60, 1} "Denominator coefficients, highest power of s first";
  parameter Boolean steady_start = true "Start in steady state (else from the initial value)";
  Modelica.Blocks.Interfaces.RealInput u "Input"
    annotation(Placement(transformation(extent = {{-140, -20}, {-100, 20}}), iconTransformation(extent = {{-140, -20}, {-100, 20}})));
  Modelica.Blocks.Interfaces.RealOutput y "Output"
    annotation(Placement(transformation(extent = {{100, -10}, {120, 10}}), iconTransformation(extent = {{100, -10}, {120, 10}})));
protected
  Modelica.Blocks.Continuous.TransferFunction tf(b = b, a = a, initType = if steady_start then Modelica.Blocks.Types.Init.SteadyState else Modelica.Blocks.Types.Init.InitialState);
equation
  connect(u, tf.u);
  connect(tf.y, y);
  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "b(s)/a(s)", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>A linear model given by its numerator and denominator in s, highest power first: b = {2}, a = {120, 1} is a gain of 2 with a 120 s lag.</p><h4>How to read it</h4><p>The gain in steady state is the last coefficient of b over the last one of a; the roots of a are the poles. It starts in steady state by default (else from zero).</p><h4>Formula</h4><pre>y = (b1·s^m + … + b(m+1)) / (a1·s^n + … + a(n+1)) · u</pre></html>"));
end TransferFunction;
