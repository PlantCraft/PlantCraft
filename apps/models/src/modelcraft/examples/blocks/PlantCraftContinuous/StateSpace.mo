within PlantCraftContinuous;
block StateSpace "State space: x' = A x + B u, y = C x + D u"
  parameter Real A[:, size(A, 1)] = {{-1}} "State matrix";
  parameter Real B[size(A, 1), 1] = {{1}} "Input matrix (one column)";
  parameter Real C[1, size(A, 1)] = {{1}} "Output matrix (one row)";
  parameter Real D[1, 1] = {{0}} "Feedthrough";
  parameter Boolean steady_start = true "Start in steady state (else from the initial value)";
  Modelica.Blocks.Interfaces.RealInput u "Input"
    annotation(Placement(transformation(extent = {{-140, -20}, {-100, 20}}), iconTransformation(extent = {{-140, -20}, {-100, 20}})));
  Modelica.Blocks.Interfaces.RealOutput y "Output"
    annotation(Placement(transformation(extent = {{100, -10}, {120, 10}}), iconTransformation(extent = {{100, -10}, {120, 10}})));
protected
  Modelica.Blocks.Continuous.StateSpace ss(A = A, B = B, C = C, D = D, initType = if steady_start then Modelica.Blocks.Types.Init.SteadyState else Modelica.Blocks.Types.Init.InitialState);
equation
  connect(u, ss.u[1]);
  connect(ss.y[1], y);
  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "x'=Ax+Bu", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>A linear model with one input and one output written as matrices, as identification tools and textbooks give it.</p><h4>How to read it</h4><p>A is the dynamics (its eigenvalues are the poles), B how the input enters, C what is measured and D the direct part. It starts in steady state by default (else from zero).</p><h4>Formula</h4><pre>dx/dt = A·x + B·u,  y = C·x + D·u</pre></html>"));
end StateSpace;
