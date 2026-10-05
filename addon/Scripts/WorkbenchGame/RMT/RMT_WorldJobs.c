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
			m_Ctx.WriteStatus("roads", "failed", 0, 0, 1, 0, 0, "could not open the roads files in " + folder);
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
		if (roads == 0)
		{
			// never an empty success: a renamed road class would look exactly like this
			string why = string.Format("no RoadEntity among %1 editor entities (and %2 road-generator shapes): the class may have been renamed, or the world has no roads", count, shapes);
			m_Ctx.WriteStatus("roads", "failed", 0, 0, 1, 0, System.GetTickCount() - t0, why);
			return 1;
		}
		m_Ctx.WriteStatus("roads", "done", 1, 0, 0, roads, System.GetTickCount() - t0);
		return 0;
	}
}

//------------------------------------------------------------------------------------------------
// sightlines/check.csv: random sight lines fired by the engine itself, so the baked line of sight can be scored
// against the game (`rmt.py check`, rmtlib/check_los.py). Port of the old Everon exporter's "Check: sight lines".
// Observers crouch (eyes 1 m up) or, three times in ten, sit in a vehicle (2 m); targets stand (chest 1.5 m); 10 m
// to 1 km apart, evenly spread on a log scale; both on land (ground at or above the water line, y >= 0: the same
// water test as the baker, so beaches count) and at least 200 m inside the terrain's edge. Two rays each: one that stops on anything (as the surface job's rays do)
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
			m_Ctx.WriteStatus("sightlines", "failed", 0, 0, 1, 0, 0, "nothing to do (no lines asked for, or the world is under 400 m)");
			return 1;
		}
		string folder = m_Ctx.m_sOut + "/sightlines";
		RMT_Context.MakeDirs(folder);
		FileHandle f = FileIO.OpenFile(folder + "/check.csv", FileMode.WRITE);
		if (!f)
		{
			m_Ctx.WriteStatus("sightlines", "failed", 0, 0, 1, 0, 0, "could not open " + folder + "/check.csv");
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
			if (og < 0)
				continue;
			float dist = Math.Pow(10, Math.RandomFloat(1, 3));
			float ang = Math.RandomFloat(0, Math.PI2);
			float tx = ox + Math.Sin(ang) * dist;
			float tz = oz + Math.Cos(ang) * dist;
			if (tx < minX || tz < minZ || tx > maxX || tz > maxZ)
				continue;
			float tg = world.GetSurfaceY(tx, tz);
			if (tg < 0)
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
			m_Ctx.WriteStatus("sightlines", "failed", 0, 0, wanted, 0, System.GetTickCount() - t0, "no land found for the sight lines");
			return 1;
		}
		RMT_Context.Say(string.Format("sightlines|lines=%1|tries=%2", made, tries));
		if (made < wanted)
		{
			// a short sample: partial, with how many lines are missing (not stored as a finished sample)
			string why = string.Format("found land for %1 of %2 lines in %3 tries", made, wanted, tries);
			m_Ctx.WriteStatus("sightlines", "partial", 1, 0, wanted - made, made, System.GetTickCount() - t0, why);
			return 0;
		}
		m_Ctx.WriteStatus("sightlines", "done", 1, 0, 0, made, System.GetTickCount() - t0);
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
			// objects and object lists first: Get() also "reads" them, as an empty string, and they would never be walked
			BaseContainerList list = bc.GetObjectArray(var);
			if (list)
			{
				for (int i = 0; i < list.Count() && i < 20; i++)
				{
					BaseContainer item = list.Get(i);
					if (item)
						DumpContainer(f, head, string.Format("%1%2[%3].", prefix, var, i), item, depth + 1);
				}
				continue;
			}
			BaseContainer child = bc.GetObject(var);
			if (child)
			{
				DumpContainer(f, head, prefix + var + ".", child, depth + 1);
				continue;
			}
			string value;
			if (bc.Get(var, value))
				f.Write(head + RMT_Context.Q(prefix + var) + "," + RMT_Context.Q(value) + "\n");
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
			m_Ctx.WriteStatus("names", "failed", 0, 0, 1, 0, 0, "could not open " + folder + "/descriptors.csv");
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

//------------------------------------------------------------------------------------------------
// conflict/entities.csv: run on a Conflict scenario world (worlds/MP/CTI_Campaign_<map>.ent), every entity whose
// prefab or components belong to the game mode (bases, radio towers, HQ starts, supply stashes, vehicle spawns,
// service points), with all of those components' settings. conflict.py turns it into the site's reference file.
//   entity,class,prefab,name,x,y,z,component,var,value   (component "" = the entity itself, listed once)
class RMT_ConflictJob
{
	protected RMT_Context m_Ctx;
	// What belongs to the game mode, matched against a prefab path's folder and file-name words and against class
	// names' words (split at capitals and underscores), never as a bare substring: "HQ" no longer matches any path that
	// happens to contain those letters, nor "Fuel" every fuel can, nor "Resource" every resource name.
	protected ref array<string> m_aKeys = {"Campaign", "Supply", "Supplies", "VehicleSpawn", "Refuel", "Repair",
		"Service", "SupportStation", "Radio", "SpawnPoint", "Spawnpoint", "Cache", "Arsenal", "MilitaryBase", "Conflict", "HQ"};
	// words that only count as part of a larger name (a fuel depot, a resource component), never alone
	protected ref array<string> m_aKeysJoined = {"FuelDepot", "FuelStation", "FuelManager", "ResourceComponent",
		"ResourceContainer", "ResourceGenerator", "ResourceConsumer"};

	void RMT_ConflictJob(RMT_Context ctx)
	{
		m_Ctx = ctx;
	}

	// The words of a class name or a path: split at "/", "_", "." and at each capital that follows a small letter.
	protected static void Words(string s, notnull array<string> words)
	{
		string word = "";
		for (int i = 0; i < s.Length(); i++)
		{
			string ch = s.Get(i);
			bool sep = ch == "/" || ch == "_" || ch == "." || ch == "{" || ch == "}" || ch == " ";
			bool cap = ch.ToAscii() >= 65 && ch.ToAscii() <= 90;
			bool prevSmall = i > 0 && s.Get(i - 1).ToAscii() >= 97 && s.Get(i - 1).ToAscii() <= 122;
			if (sep || (cap && prevSmall))
			{
				if (word != "")
					words.Insert(word);
				word = "";
				if (sep)
					continue;
			}
			word += ch;
		}
		if (word != "")
			words.Insert(word);
	}

	protected bool Wanted(string s)
	{
		if (s == "")
			return false;
		foreach (string j : m_aKeysJoined)
		{
			if (s.Contains(j))
				return true;
		}
		array<string> words = {};
		Words(s, words);
		// a key may be one word ("Radio") or two run together ("VehicleSpawn", "MilitaryBase"): match against single
		// words and against each pair of neighbours
		for (int i = 0; i < words.Count(); i++)
		{
			string pair = "";
			if (i + 1 < words.Count())
				pair = words[i] + words[i + 1];
			foreach (string k : m_aKeys)
			{
				if (words[i] == k || pair == k)
					return true;
			}
		}
		return false;
	}

	protected void DumpContainer(FileHandle f, string head, string prefix, BaseContainer bc, int depth)
	{
		if (!bc || depth > 3)
			return;
		int n = bc.GetNumVars();
		for (int v = 0; v < n; v++)
		{
			string var = bc.GetVarName(v);
			// object lists first: Get() also "reads" them, as an empty string
			BaseContainerList list = bc.GetObjectArray(var);
			if (list)
			{
				for (int i = 0; i < list.Count() && i < 20; i++)
				{
					BaseContainer item = list.Get(i);
					if (!item)
						continue;
					f.Write(head + RMT_Context.Q(string.Format("%1%2[%3]._class", prefix, var, i)) + "," + RMT_Context.Q(item.GetClassName()) + "\n");
					DumpContainer(f, head, string.Format("%1%2[%3].", prefix, var, i), item, depth + 1);
				}
				continue;
			}
			BaseContainer child = bc.GetObject(var);
			if (child)
			{
				DumpContainer(f, head, prefix + var + ".", child, depth + 1);
				continue;
			}
			string value;
			if (bc.Get(var, value))
				f.Write(head + RMT_Context.Q(prefix + var) + "," + RMT_Context.Q(value) + "\n");
		}
	}

	// One entity, if its prefab, class or a component is wanted: a "_parent" row, then a "_component" row per
	// component and the settings of the wanted ones. False if it was not wanted.
	protected bool DumpSource(FileHandle f, int id, IEntitySource src, IEntity ent)
	{
		string prefab = "";
		BaseContainer anc = src.GetAncestor();
		if (anc)
			prefab = anc.GetResourceName();
		if (prefab == "" && ent)
			prefab = RMT_Context.PrefabOf(ent);
		string cls = src.GetClassName();
		bool any = Wanted(prefab) || Wanted(cls);
		int nc = src.GetComponentCount();
		for (int c = 0; c < nc && !any; c++)
		{
			IEntityComponentSource comp = src.GetComponent(c);
			if (comp && Wanted(comp.GetClassName()))
				any = true;
		}
		if (!any)
			return false;
		vector o = "0 0 0";
		if (ent)
			o = ent.GetOrigin();
		string parent = "";
		IEntitySource par = src.GetParent();
		if (par)
		{
			BaseContainer pa = par.GetAncestor();
			if (pa)
				parent = pa.GetResourceName();
		}
		if (parent == "" && ent && ent.GetParent())
			parent = RMT_Context.PrefabOf(ent.GetParent());
		string head = string.Format("%1,%2,%3,%4,%5,%6,%7,", id, RMT_Context.Q(cls), RMT_Context.Q(prefab), RMT_Context.Q(src.GetName()), o[0], o[1], o[2]);
		f.Write(head + ",_parent," + RMT_Context.Q(parent) + "\n");
		for (int c2 = 0; c2 < nc; c2++)
		{
			IEntityComponentSource comp2 = src.GetComponent(c2);
			if (!comp2)
				continue;
			string ccls = comp2.GetClassName();
			f.Write(head + RMT_Context.Q(ccls) + ",_component,\n");
			if (Wanted(ccls))
				DumpContainer(f, head + RMT_Context.Q(ccls) + ",", "", comp2, 0);
		}
		return true;
	}

	int Run()
	{
		float t0 = System.GetTickCount();
		string folder = m_Ctx.m_sOut + "/conflict";
		RMT_Context.MakeDirs(folder);
		FileHandle f = FileIO.OpenFile(folder + "/entities.csv", FileMode.WRITE);
		if (!f)
		{
			m_Ctx.WriteStatus("conflict", "failed", 0, 0, 1, 0, 0, "could not open " + folder + "/entities.csv");
			return 1;
		}
		f.Write("entity,class,prefab,name,x,y,z,component,var,value\n");
		int count = m_Ctx.m_Api.GetEditorEntityCount();
		int found = 0;
		set<IEntity> done = new set<IEntity>();
		for (int i = 0; i < count; i++)
		{
			if (i % 100000 == 0)
				RMT_Context.Say(string.Format("progress|conflict|%1|%2", i, count));
			IEntitySource src = m_Ctx.m_Api.GetEditorEntity(i);
			if (!src)
				continue;
			IEntity ent = m_Ctx.m_Api.SourceToEntity(src);
			if (ent)
				done.Insert(ent);
			if (DumpSource(f, found, src, ent))
				found++;
		}
		// The entities a placed prefab brings with it (a supply cache composition's crates, a base's fuel pumps) are
		// not editor entities: they are found in the world, chunk by chunk, and read through their own source.
		int extra = 0;
		for (int tz = 0; tz < m_Ctx.m_iRows; tz++)
		{
			for (int tx = 0; tx < m_Ctx.m_iCols; tx++)
			{
				float x0 = m_Ctx.ChunkX(tx);
				float z0 = m_Ctx.ChunkZ(tz);
				array<IEntity> ents = m_Ctx.Query(x0, z0, x0 + m_Ctx.m_fTile, z0 + m_Ctx.m_fTile);
				foreach (IEntity e : ents)
				{
					vector eo = e.GetOrigin();
					// each entity once: in the chunk holding its origin
					if (eo[0] < x0 || eo[2] < z0 || eo[0] >= x0 + m_Ctx.m_fTile || eo[2] >= z0 + m_Ctx.m_fTile)
						continue;
					if (done.Contains(e))
						continue;
					IEntitySource es = m_Ctx.m_Api.EntityToSource(e);
					if (es && DumpSource(f, found, es, e))
					{
						found++;
						extra++;
					}
				}
			}
			RMT_Context.Say(string.Format("progress|conflict|%1|%2", tz + 1, m_Ctx.m_iRows));
		}
		RMT_Context.Say(string.Format("conflict|inside prefabs=%1", extra));
		f.Close();
		RMT_Context.Say(string.Format("conflict|entities=%1", found));
		m_Ctx.WriteStatus("conflict", "done", 1, 0, 0, found, System.GetTickCount() - t0);
		return 0;
	}
}
