// Jobs that walk the whole world once instead of chunk by chunk.

//------------------------------------------------------------------------------------------------
// roads/: every road piece exactly as the world stores it (port of the old EveronRoadExportTool, which found all
// 2370 RoadEntity pieces on Everon, nested under road generators or not).
//   roadentities.csv  road,which,material,width,type,point,x,y,z   (which = ctrl: spline point; curve: shape curve)
//   roadboxes.csv     road,prefab,parent,x,y,z,minx,miny,minz,maxx,maxy,maxz
//   splines.csv       road,shape,generator,point,x,y,z   (editable spline shapes that carry a road generator)
// Decals painted by the same road system (beach debris, flower beds, runway marks) are kept here and dropped by
// material when baking.
class RMT_RoadsJob
{
	protected RMT_Context m_Ctx;

	void RMT_RoadsJob(RMT_Context ctx)
	{
		m_Ctx = ctx;
	}

	protected string PrefabOfSource(IEntitySource src)
	{
		BaseContainer anc = src.GetAncestor();
		if (!anc)
			return "";
		return anc.GetResourceName();
	}

	protected string RoadGeneratorOf(IEntitySource src)
	{
		int n = src.GetNumChildren();
		for (int i = 0; i < n; i++)
		{
			IEntitySource child = src.GetChild(i);
			if (!child)
				continue;
			string cls = child.GetClassName();
			if (cls.Contains("RoadGenerator"))
			{
				string prefab = PrefabOfSource(child);
				if (prefab == "")
					return cls;
				return prefab;
			}
		}
		return "";
	}

	protected int ExportRoadEntity(IEntitySource src, int id, FileHandle fr, FileHandle fb)
	{
		IEntity ent = m_Ctx.m_Api.SourceToEntity(src);
		if (!ent)
			return 0;
		string parent = "";
		IEntitySource par = src.GetParent();
		if (par)
			parent = par.GetClassName();
		vector wmin, wmax;
		ent.GetWorldBounds(wmin, wmax);
		vector o = ent.GetOrigin();
		string line = string.Format("%1,%2,%3,%4,%5,%6,", id, RMT_Context.Q(PrefabOfSource(src)), RMT_Context.Q(parent), o[0], o[1], o[2]);
		line += string.Format("%1,%2,%3,%4,%5,%6\n", wmin[0], wmin[1], wmin[2], wmax[0], wmax[1], wmax[2]);
		fb.Write(line);

		string material;
		src.Get("Material", material);
		material = RMT_Context.Q(material);
		float width;
		src.Get("Width", width);
		int type;
		src.Get("Type", type);
		vector mat[4];
		ent.GetWorldTransform(mat);
		int written = 0;
		ShapeEntity shape = ShapeEntity.Cast(ent);
		if (shape)
		{
			array<vector> curve = {};
			shape.GenerateTesselatedShape(curve);
			for (int p = 0; p < curve.Count(); p++)
			{
				vector w = curve[p].Multiply4(mat);
				fr.Write(string.Format("%1,curve,%2,%3,%4,%5,%6,%7,%8\n", id, material, width, type, p, w[0], w[1], w[2]));
				written++;
			}
		}
		BaseContainerList spl = src.GetObjectArray("SplinePoints");
		if (spl)
		{
			for (int q = 0; q < spl.Count(); q++)
			{
				BaseContainer sp = spl.Get(q);
				vector local;
				sp.Get("Position", local);
				vector ws = local.Multiply4(mat);
				fr.Write(string.Format("%1,ctrl,%2,%3,%4,%5,%6,%7,%8\n", id, material, width, type, q, ws[0], ws[1], ws[2]));
				written++;
			}
		}
		return written;
	}

	int Run()
	{
		float t0 = System.GetTickCount();
		string folder = m_Ctx.m_sOut + "/roads";
		RMT_Context.MakeDirs(folder);
		FileHandle fr = FileIO.OpenFile(folder + "/roadentities.csv", FileMode.WRITE);
		FileHandle fb = FileIO.OpenFile(folder + "/roadboxes.csv", FileMode.WRITE);
		FileHandle fs = FileIO.OpenFile(folder + "/splines.csv", FileMode.WRITE);
		if (!fr || !fb || !fs)
		{
			m_Ctx.WriteStatus("roads", "failed", 0, 0, 1, 0, 0);
			return 1;
		}
		fr.Write("road,which,material,width,type,point,x,y,z\n");
		fb.Write("road,prefab,parent,x,y,z,minx,miny,minz,maxx,maxy,maxz\n");
		fs.Write("road,shape,generator,point,x,y,z\n");
		int count = m_Ctx.m_Api.GetEditorEntityCount();
		int roads = 0;
		int points = 0;
		int shapes = 0;
		for (int i = 0; i < count; i++)
		{
			if (i % 100000 == 0)
				RMT_Context.Say(string.Format("progress|roads|%1|%2", i, count));
			IEntitySource src = m_Ctx.m_Api.GetEditorEntity(i);
			if (!src)
				continue;
			string cls = src.GetClassName();
			if (cls.Contains("RoadEntity"))
			{
				points += ExportRoadEntity(src, roads, fr, fb);
				roads++;
				continue;
			}
			if (!cls.Contains("ShapeEntity"))
				continue;
			string gen = RoadGeneratorOf(src);
			if (gen == "")
				continue;
			ShapeEntity shape = ShapeEntity.Cast(m_Ctx.m_Api.SourceToEntity(src));
			if (!shape)
				continue;
			vector mat[4];
			shape.GetWorldTransform(mat);
			array<vector> curve = {};
			shape.GenerateTesselatedShape(curve);
			for (int p = 0; p < curve.Count(); p++)
			{
				vector w = curve[p].Multiply4(mat);
				fs.Write(string.Format("%1,%2,%3,%4,%5,%6,%7\n", shapes, cls, RMT_Context.Q(gen), p, w[0], w[1], w[2]));
			}
			shapes++;
		}
		fr.Close();
		fb.Close();
		fs.Close();
		RMT_Context.Say(string.Format("roads|pieces=%1|points=%2|shapes=%3", roads, points, shapes));
		m_Ctx.WriteStatus("roads", "done", 1, 0, 0, roads, System.GetTickCount() - t0);
		return 0;
	}
}

//------------------------------------------------------------------------------------------------
// names/descriptors.csv: every entity carrying a map-descriptor component (town names, map labels, map symbols),
// with all of that component's settings, so the baker can pick out place names without guessing property names.
//   entity,class,prefab,name,x,y,z,component,var,value
class RMT_NamesJob
{
	protected RMT_Context m_Ctx;

	void RMT_NamesJob(RMT_Context ctx)
	{
		m_Ctx = ctx;
	}

	protected void DumpContainer(FileHandle f, string head, string prefix, BaseContainer bc, int depth)
	{
		if (!bc || depth > 3)
			return;
		int n = bc.GetNumVars();
		for (int v = 0; v < n; v++)
		{
			string var = bc.GetVarName(v);
			string value;
			if (bc.Get(var, value))
			{
				f.Write(head + RMT_Context.Q(prefix + var) + "," + RMT_Context.Q(value) + "\n");
				continue;
			}
			BaseContainer child = bc.GetObject(var);
			if (child)
				DumpContainer(f, head, prefix + var + ".", child, depth + 1);
		}
	}

	int Run()
	{
		float t0 = System.GetTickCount();
		string folder = m_Ctx.m_sOut + "/names";
		RMT_Context.MakeDirs(folder);
		FileHandle f = FileIO.OpenFile(folder + "/descriptors.csv", FileMode.WRITE);
		if (!f)
		{
			m_Ctx.WriteStatus("names", "failed", 0, 0, 1, 0, 0);
			return 1;
		}
		f.Write("entity,class,prefab,name,x,y,z,component,var,value\n");
		int count = m_Ctx.m_Api.GetEditorEntityCount();
		int found = 0;
		for (int i = 0; i < count; i++)
		{
			if (i % 100000 == 0)
				RMT_Context.Say(string.Format("progress|names|%1|%2", i, count));
			IEntitySource src = m_Ctx.m_Api.GetEditorEntity(i);
			if (!src)
				continue;
			int nc = src.GetComponentCount();
			for (int c = 0; c < nc; c++)
			{
				IEntityComponentSource comp = src.GetComponent(c);
				if (!comp)
					continue;
				string ccls = comp.GetClassName();
				if (!ccls.Contains("MapDescriptor"))
					continue;
				IEntity ent = m_Ctx.m_Api.SourceToEntity(src);
				vector o = "0 0 0";
				if (ent)
					o = ent.GetOrigin();
				BaseContainer anc = src.GetAncestor();
				string prefab = "";
				if (anc)
					prefab = anc.GetResourceName();
				string head = string.Format("%1,%2,%3,%4,%5,%6,%7,%8,", found, RMT_Context.Q(src.GetClassName()), RMT_Context.Q(prefab), RMT_Context.Q(src.GetName()), o[0], o[1], o[2], RMT_Context.Q(ccls));
				DumpContainer(f, head, "", comp, 0);
				// The display name is a string-table key ("#AR-MapLocation_...") and the type an enum number;
				// write the text and the type name too.
				string key;
				comp.Get("DisplayName", key);
				if (key != "")
					f.Write(head + "_text," + RMT_Context.Q(WidgetManager.Translate(key)) + "\n");
				int mainType;
				if (comp.Get("MainType", mainType))
					f.Write(head + "_type," + typename.EnumToString(EMapDescriptorType, mainType) + "\n");
				found++;
			}
		}
		f.Close();
		RMT_Context.Say(string.Format("names|descriptors=%1", found));
		m_Ctx.WriteStatus("names", "done", 1, 0, 0, found, System.GetTickCount() - t0);
		return 0;
	}
}
