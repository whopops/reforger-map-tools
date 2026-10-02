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
// sightlines/check.csv: random sight lines fired by the engine itself, so the baked line of sight can be scored
// against the game (`rmt.py check`, rmtlib/check_los.py). Port of the old Everon exporter's "Check: sight lines".
// Observers crouch (eyes 1 m up) or, three times in ten, sit in a vehicle (2 m); targets stand (chest 1.5 m); 10 m
// to 1 km apart, evenly spread on a log scale; both on land (ground at least 1 m above the water line) and at
// least 200 m inside the terrain's edge. Two rays each: one that stops on anything (as the surface job's rays do)
// and one that stops only on what stops bullets. The seed is fixed, so a rerun on the same world fires the same lines.
//   ox,oz,og,eye,tx,tz,tg,target,dist,frac_all,hit_all,frac_bullet
// frac_*: how far along the ray got (1 = clear); hit_all: the class of what stopped the first ray.
// -rmtSightLines=N sets how many lines (default 20000).
class RMT_SightLinesJob
{
	protected RMT_Context m_Ctx;

	void RMT_SightLinesJob(RMT_Context ctx)
	{
		m_Ctx = ctx;
	}

	protected float Trace(vector from, vector to, int mask, out IEntity hit)
	{
		TraceParam p = new TraceParam();
		p.Start = from;
		p.End = to;
		p.Flags = TraceFlags.WORLD | TraceFlags.ENTS;
		p.LayerMask = mask;
		float frac = m_Ctx.m_World.TraceMove(p, null);
		hit = p.TraceEnt;
		return frac;
	}

	int Run()
	{
		float t0 = System.GetTickCount();
		int wanted = m_Ctx.Arg("-rmtSightLines", "20000").ToInt();
		float minX = m_Ctx.m_vMin[0];
		float minZ = m_Ctx.m_vMin[2];
		float maxX = m_Ctx.m_vMax[0];
		float maxZ = m_Ctx.m_vMax[2];
		if (wanted < 1 || maxX - minX <= 400 || maxZ - minZ <= 400)
		{
			RMT_Context.Say("error|sightlines|nothing to do (no lines asked for, or the world is under 400 m)");
			m_Ctx.WriteStatus("sightlines", "failed", 0, 0, 1, 0, 0);
			return 1;
		}
		string folder = m_Ctx.m_sOut + "/sightlines";
		RMT_Context.MakeDirs(folder);
		FileHandle f = FileIO.OpenFile(folder + "/check.csv", FileMode.WRITE);
		if (!f)
		{
			m_Ctx.WriteStatus("sightlines", "failed", 0, 0, 1, 0, 0);
			return 1;
		}
		f.Write("ox,oz,og,eye,tx,tz,tg,target,dist,frac_all,hit_all,frac_bullet\n");
		BaseWorld world = m_Ctx.m_World;
		Math.Randomize(12345);
		int made = 0;
		int tries = 0;
		while (made < wanted && tries < wanted * 20)
		{
			tries++;
			float ox = Math.RandomFloat(minX + 200, maxX - 200);
			float oz = Math.RandomFloat(minZ + 200, maxZ - 200);
			float og = world.GetSurfaceY(ox, oz);
			if (og < 1)
				continue;
			float dist = Math.Pow(10, Math.RandomFloat(1, 3));
			float ang = Math.RandomFloat(0, Math.PI2);
			float tx = ox + Math.Sin(ang) * dist;
			float tz = oz + Math.Cos(ang) * dist;
			if (tx < minX || tz < minZ || tx > maxX || tz > maxZ)
				continue;
			float tg = world.GetSurfaceY(tx, tz);
			if (tg < 1)
				continue;
			float eye = 1;
			if (Math.RandomFloat01() < 0.3)
				eye = 2;
			float target = 1.5;
			vector from = Vector(ox, og + eye, oz);
			vector to = Vector(tx, tg + target, tz);
			IEntity hit;
			float fa = Trace(from, to, 0xFFFFFFFF, hit);
			string hitCls = "";
			if (hit)
				hitCls = hit.ClassName();
			IEntity bhit;
			float fb = Trace(from, to, EPhysicsLayerPresets.Projectile, bhit);
			string line = string.Format("%1,%2,%3,%4,%5,%6,%7,%8,", ox, oz, og, eye, tx, tz, tg, target);
			line += string.Format("%1,%2,%3,%4\n", dist, fa, RMT_Context.Q(hitCls), fb);
			f.Write(line);
			made++;
			if (made % 1000 == 0)
				RMT_Context.Say(string.Format("progress|sightlines|%1|%2", made, wanted));
		}
		f.Close();
		if (made == 0)
		{
			RMT_Context.Say("error|sightlines|no land found for the sight lines");
			m_Ctx.WriteStatus("sightlines", "failed", 0, 0, 1, 0, System.GetTickCount() - t0);
			return 1;
		}
		string result = "done";
		if (made < wanted)
			result = "partial";
		RMT_Context.Say(string.Format("sightlines|lines=%1|tries=%2", made, tries));
		m_Ctx.WriteStatus("sightlines", result, 1, 0, 0, made, System.GetTickCount() - t0);
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
