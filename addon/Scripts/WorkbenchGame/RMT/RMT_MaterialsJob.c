// materials (research, not in the pipeline): every parameter of the listed resources, with the value the resource
// sets and the class default, so a measurement can use the alpha test, fade and opacity settings the game uses even
// where a material leaves them unset (a tree crown's .emat sets no AlphaTest; the shader class default applies).
//   -rmtList=<profile-relative file>   one resource name per line ({GUID}path.emat, .edds, .et ...)
//   materials/params.csv               resource,class,var,set,value,default
//                                      set: 1 if the resource (or an ancestor) sets it, 0 if it is the class default
//   materials/meta.csv                 resource,var,value: the resource's .meta (import settings) where Workbench has one
class RMT_MaterialsJob
{
	protected RMT_Context m_Ctx;

	void RMT_MaterialsJob(RMT_Context ctx)
	{
		m_Ctx = ctx;
	}

	protected void Dump(FileHandle f, string head, string prefix, BaseContainer bc, int depth)
	{
		if (!bc || depth > 4)
			return;
		for (int v = 0, n = bc.GetNumVars(); v < n; v++)
		{
			string var = bc.GetVarName(v);
			BaseContainerList list = bc.GetObjectArray(var);
			if (list)
			{
				for (int i = 0; i < list.Count() && i < 40; i++)
					Dump(f, head, string.Format("%1%2[%3].", prefix, var, i), list.Get(i), depth + 1);
				continue;
			}
			BaseContainer child = bc.GetObject(var);
			if (child)
			{
				Dump(f, head, prefix + var + ".", child, depth + 1);
				continue;
			}
			string value, def;
			bc.Get(var, value);
			bc.GetDefaultAsString(var, def);
			int isSet = 0;
			if (bc.IsVariableSet(var))
				isSet = 1;
			f.WriteLine(head + RMT_Context.Q(prefix + var) + "," + isSet.ToString() + "," + RMT_Context.Q(value) + "," + RMT_Context.Q(def));
		}
	}

	int Run()
	{
		float t0 = System.GetTickCount();
		string folder = m_Ctx.m_sOut + "/materials";
		RMT_Context.MakeDirs(folder);
		string listPath = "$profile:" + m_Ctx.Arg("-rmtList", "rmt/_materials/list.txt");
		FileHandle list = FileIO.OpenFile(listPath, FileMode.READ);
		if (!list)
		{
			m_Ctx.WriteStatus("materials", "failed", 0, 0, 1, 0, 0, "no list " + listPath);
			return 1;
		}
		FileHandle f = FileIO.OpenFile(folder + "/params.csv", FileMode.WRITE);
		FileHandle fm = FileIO.OpenFile(folder + "/meta.csv", FileMode.WRITE);
		if (!f || !fm)
		{
			list.Close();
			m_Ctx.WriteStatus("materials", "failed", 0, 0, 1, 0, 0, "could not open the output files in " + folder);
			return 1;
		}
		f.WriteLine("resource,class,var,set,value,default");
		fm.WriteLine("resource,var,set,value,default");
		ResourceManager rm = Workbench.GetModule(ResourceManager);
		string line;
		int done, bad, metas;
		while (list.ReadLine(line) >= 0)
		{
			line.Trim();
			if (line == "")
				continue;
			Resource res = Resource.Load(line);
			if (!res || !res.IsValid() || !res.GetResource())
			{
				bad++;
				RMT_Context.Say("materials|error|could not load " + line);
				continue;
			}
			BaseContainer bc = res.GetResource().ToBaseContainer();
			if (!bc)
			{
				bad++;
				continue;
			}
			Dump(f, RMT_Context.Q(line) + "," + RMT_Context.Q(bc.GetClassName()) + ",", "", bc, 0);
			done++;
			if (rm)
			{
				MetaFile meta = rm.GetMetaFile(line);
				if (meta)
				{
					Dump(fm, RMT_Context.Q(line) + ",", "", meta, 0);
					metas++;
				}
			}
		}
		list.Close();
		f.Close();
		fm.Close();
		RMT_Context.Say(string.Format("materials|done=%1|bad=%2|metas=%3", done, bad, metas));
		if (done == 0)
		{
			m_Ctx.WriteStatus("materials", "failed", 0, bad, 1, 0, System.GetTickCount() - t0, "no resource could be read");
			return 1;
		}
		string result = "done";
		string reason = "";
		if (bad > 0)
		{
			result = "partial";
			reason = string.Format("%1 resource(s) could not be read", bad);
		}
		m_Ctx.WriteStatus("materials", result, done, 0, bad, done, System.GetTickCount() - t0, reason);
		return 0;
	}
}
