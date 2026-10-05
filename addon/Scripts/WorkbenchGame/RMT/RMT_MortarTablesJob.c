// Engine firing-table lookup for the offline website producer. No actual shots are fired.
// plan: id,prefab,coef,min,max,step,mils. output: mortar_tables/tables.csv, id,range,elevation,time,delevation.
// Only the high register is written: angles of 45-85 degrees (the M252's and the 2B14's LimitsVert 45 85); the low
// register (under 45 degrees) is never in the file.
// delevation: the change of elevation (mils) for 100 m more range, from the sample 50 m further on, doubled (the
// website's delev_mil_per_100m). Left EMPTY when there is no sample 50 m on (the end of the table), never written as 0.
// A page (one shell and charge) that cannot be read, or gives fewer than 2 rows, is skipped and named in the status
// ("bad_pages"); the job is partial if any page succeeded (remaining = pages skipped), failed if none did.
class RMT_MortarTablesJob
{
	protected RMT_Context m_Ctx;
	void RMT_MortarTablesJob(RMT_Context ctx) { m_Ctx = ctx; }
	int Run()
	{
		float started = System.GetTickCount();
		string dir = m_Ctx.m_sOut + "/mortar_tables";
		RMT_Context.MakeDirs(dir);
		string planPath = "$profile:" + m_Ctx.Arg("-rmtMortarPlan", "rmt/_mortar/plan.csv");
		FileHandle plan = FileIO.OpenFile(planPath, FileMode.READ);
		if (!plan)
		{
			m_Ctx.WriteStatus("mortar_tables", "failed", 0, 0, 1, 0, 0, "no plan " + planPath);
			return 1;
		}
		FileHandle output = FileIO.OpenFile(dir + "/tables.csv", FileMode.WRITE);
		if (!output)
		{
			plan.Close();
			m_Ctx.WriteStatus("mortar_tables", "failed", 0, 0, 1, 0, 0, "could not open " + dir + "/tables.csv");
			return 1;
		}
		output.WriteLine("id,range,elevation,time,delevation");
		string line;
		int rows, pages, good;
		array<string> bad = {};
		plan.ReadLine(line);
		while (plan.ReadLine(line) >= 0)
		{
			array<string> cols = {};
			line.Split(",", cols, false);
			if (cols.Count() < 1 || line == "")
				continue;
			pages++;
			string id = cols[0];
			if (cols.Count() != 7) { bad.Insert(id + ": not 7 columns"); continue; }
			Resource res = Resource.Load(cols[1]);
			if (!res.IsValid()) { bad.Insert(id + ": no prefab"); continue; }
			IEntitySource src = res.GetResource().ToEntitySource();
			if (!src) { bad.Insert(id + ": no entity source"); continue; }
			float coef = cols[2].ToFloat();
			float mils = cols[6].ToFloat();
			int step = cols[5].ToInt();
			if (coef <= 0 || mils <= 0 || step < 1) { bad.Insert(id + ": bad coef, mils or step"); continue; }
			array<string> lines = {};
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
				string change = "";
				if (nextTime > 0 && nextHeight > 0)
					change = Math.Round((angle - Math.Atan2(nextHeight, distance + 50)) * mils / (2 * Math.PI) * 2).ToString();
				lines.Insert(string.Format("%1,%2,%3,%4,%5", id, distance, Math.Round(angle * mils / (2 * Math.PI)), time.ToString(0, 1), change));
			}
			if (lines.Count() < 2)
			{
				bad.Insert(string.Format("%1: %2 rows", id, lines.Count()));
				continue;
			}
			foreach (string l : lines)
				output.WriteLine(l);
			rows += lines.Count();
			good++;
			RMT_Context.Say(string.Format("mortar_tables|page=%1|rows=%2|bad=%3", pages, rows, bad.Count()));
		}
		plan.Close();
		output.Close();
		string badList = "";
		foreach (int i, string b : bad)
		{
			if (i > 0)
				badList += "\", \"";
			string e = b;
			e.Replace("\"", "'");
			badList += e;
		}
		string extra = "  \"bad_pages\": [";
		if (badList != "")
			extra += "\"" + badList + "\"";
		extra += "],";
		string result = "done";
		string reason = "";
		if (good == 0)
		{
			result = "failed";
			reason = string.Format("no page gave a table (%1 pages)", pages);
		}
		else if (bad.Count() > 0)
		{
			result = "partial";
			reason = string.Format("%1 of %2 pages skipped", bad.Count(), pages);
		}
		m_Ctx.WriteStatus("mortar_tables", result, good, 0, bad.Count(), rows, System.GetTickCount() - started, reason, extra);
		if (good == 0)
			return 1;
		return 0;
	}
}
