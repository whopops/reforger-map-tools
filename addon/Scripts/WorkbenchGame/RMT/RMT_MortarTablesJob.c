// Engine firing-table lookup for the offline website producer. No actual shots are fired.
// plan: id,prefab,coef,min,max,step,mils. output: id,range,elevation,time,delevation.
class RMT_MortarTablesJob
{
	protected RMT_Context m_Ctx;
	void RMT_MortarTablesJob(RMT_Context ctx) { m_Ctx = ctx; }
	int Run()
	{
		float started = System.GetTickCount();
		string dir = m_Ctx.m_sOut + "/mortar_tables";
		RMT_Context.MakeDirs(dir);
		FileHandle plan = FileIO.OpenFile("$profile:" + m_Ctx.Arg("-rmtMortarPlan", "rmt/_mortar/plan.csv"), FileMode.READ);
		if (!plan) return 1;
		FileHandle output = FileIO.OpenFile(dir + "/tables.csv", FileMode.WRITE);
		if (!output) { plan.Close(); return 1; }
		output.WriteLine("id,range,elevation,time,delevation");
		string line;
		int rows, failed, pages;
		plan.ReadLine(line);
		while (plan.ReadLine(line) >= 0)
		{
			array<string> cols = {};
			line.Split(",", cols, false);
			if (cols.Count() != 7) { failed++; continue; }
			Resource res = Resource.Load(cols[1]);
			if (!res.IsValid()) { failed++; continue; }
			IEntitySource src = res.GetResource().ToEntitySource();
			if (!src) { failed++; continue; }
			float coef = cols[2].ToFloat();
			float mils = cols[6].ToFloat();
			int step = cols[5].ToInt();
			if (coef <= 0 || mils <= 0 || step < 1) { failed++; continue; }
			int pageRows;
			for (int distance = cols[3].ToInt(); distance <= cols[4].ToInt(); distance += step)
			{
				if (distance <= 0) continue;
				float time;
				float height = BallisticTable.GetHeightFromProjectileSource(distance, time, src, coef, false);
				if (time <= 0 || height <= 0) continue;
				float angle = Math.Atan2(height, distance);
				if (angle > 85 * Math.DEG2RAD || angle < 45 * Math.DEG2RAD) continue;
				float nextTime;
				float nextHeight = BallisticTable.GetHeightFromProjectileSource(distance + 50, nextTime, src, coef, false);
				float change;
				if (nextTime > 0 && nextHeight > 0)
					change = (angle - Math.Atan2(nextHeight, distance + 50)) * mils / (2 * Math.PI) * 2;
				output.WriteLine(string.Format("%1,%2,%3,%4,%5", cols[0], distance,
					Math.Round(angle * mils / (2 * Math.PI)), time.ToString(0, 1), Math.Round(change)));
				rows++; pageRows++;
			}
			if (pageRows < 2) failed++;
			pages++;
			RMT_Context.Say(string.Format("mortar_tables|page=%1|rows=%2|failed=%3", pages, rows, failed));
		}
		plan.Close(); output.Close();
		string result = "done";
		if (failed > 0 || rows == 0) result = "failed";
		m_Ctx.WriteStatus("mortar_tables", result, 1, 0, 0, rows, System.GetTickCount() - started);
		if (failed > 0 || rows == 0) return 1;
		return 0;
	}
}
