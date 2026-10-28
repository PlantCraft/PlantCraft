within PlantCraftSources;
block TimeTable "Table: a value given at times, joined by straight lines"
  parameter Real table[:, 2] = {{0, 0}, {3600, 1}} "Rows of time (s) and value, times increasing";
  Modelica.Blocks.Interfaces.RealOutput y "Value"
    annotation(Placement(transformation(extent = {{100, -10}, {120, 10}}), iconTransformation(extent = {{100, -10}, {120, 10}})));
equation
  y = Modelica.Math.Vectors.interpolate(table[:, 1], table[:, 2], min(max(time, table[1, 1]), table[size(table, 1), 1]));
  annotation(
    Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 127}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-90, 30}, {90, -30}}, textString = "table", textColor = {0, 0, 127}), Text(extent = {{-150, 150}, {150, 110}}, textString = "%name", textColor = {0, 0, 255})}),
    Documentation(info = "<html><p>A value given at times, joined by straight lines: a recorded profile or a planned sequence.</p><h4>How to read it</h4><p>The output follows the table's rows, interpolated linearly between them; before the first row it keeps the first value, after the last row the last one.</p><h4>Formula</h4><pre>y(t) = linear interpolation of the rows (time, value)</pre></html>"));
end TimeTable;
