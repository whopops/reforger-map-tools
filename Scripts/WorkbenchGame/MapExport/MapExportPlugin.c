// Map export. Workbench runs this from -plugin, not a tool button:
//   ArmaReforgerWorkbenchSteam.exe -wbModule=WorldEditor -run -load "<world>" -plugin=MapExportPlugin -job=buildings -size=12800 -tile=500 -buildingStep=2 -maxTiles=2 -out=$profile:reforger_map/everon
// Jobs: buildings, roads, satellite.
// The world is whatever -load opened. Confirm it before putting it in maps/everon.json.
// If nine boxes across the island hold almost no entities, exit 3 and write nothing.
// Every string.Format stays at 9 arguments or fewer.

[WorkbenchPluginAttribute(name: "Map Export", description: "Export buildings, roads, and satellite shots", wbModules: {"WorldEditor"}, awesomeFontCode: 0xf1ad)]
class MapExportPlugin : WorldEditorPlugin
{
	[Attribute("buildings", UIWidgets.EditBox, "Job: buildings, roads, or satellite", category: "Export")]
	protected string m_sJob;

	[Attribute("12800", UIWidgets.EditBox, "Island square, metres", category: "Export")]
	protected float m_fSize;

	[Attribute("500", UIWidgets.EditBox, "Tile size, metres", category: "Export")]
	protected float m_fTile;

	[Attribute("2", UIWidgets.EditBox, "Floor ray and gap spacing, metres", category: "Export")]
	protected float m_fStep;

	[Attribute("2", UIWidgets.EditBox, "Stop after this many new tiles (0 = all)", category: "Export")]
	protected int m_iMaxTiles;

	[Attribute("$profile:reforger_map/everon", UIWidgets.EditBox, "Output folder", category: "Export")]
	protected string m_sOut;

	[Attribute("0", UIWidgets.EditBox, "Satellite camera height in metres (0 = from tile and fov)", category: "Satellite")]
	protected float m_fCamHeight;

	[Attribute("15", UIWidgets.EditBox, "Satellite vertical field of view, degrees", category: "Satellite")]
	protected float m_fFov;

	protected WorldEditor m_Editor;
	protected WorldEditorAPI m_Api;
	protected BaseWorld m_World;
	protected ref array<IEntity> m_aFound = new array<IEntity>();
	protected int m_iProbeCount;

	protected ref array<string> m_aRId = new array<string>();
	protected ref array<string> m_aRRole = new array<string>();
	protected ref array<string> m_aRCls = new array<string>();
	protected ref array<string> m_aRPrefab = new array<string>();
	protected ref array<string> m_aRParent = new array<string>();
	protected ref array<string> m_aRMat = new array<string>();
	protected ref array<float> m_aRWidth = new array<float>();
	protected ref array<int> m_aRType = new array<int>();
	protected ref array<vector> m_aROrigin = new array<vector>();
	protected ref array<float> m_aRYaw = new array<float>();
	protected ref array<vector> m_aRMin = new array<vector>();
	protected ref array<vector> m_aRMax = new array<vector>();
	protected ref array<int> m_aRTx = new array<int>();
	protected ref array<int> m_aRTz = new array<int>();
	protected ref array<int> m_aPRoad = new array<int>();
	protected ref array<string> m_aPWhich = new array<string>();
	protected ref array<int> m_aPI = new array<int>();
	protected ref array<vector> m_aPPos = new array<vector>();
	protected ref map<string, int> m_mSeen = new map<string, int>();
	protected int m_iDirt;
	protected int m_iBridge;
	protected int m_iDirtLine;
	protected int m_iBridgeLine;
	protected bool m_bFoundSurface;
	protected string m_sPullMat;
	protected string m_sPullPrefab;
	protected string m_sPullCls;
	protected float m_fPullWidth;
	protected int m_iPullType;

	override void Run()
	{
		Export(false);
	}

	override void RunCommandline()
	{
		ReadCmdLine();
		Export(true);
	}

	protected void ReadCmdLine()
	{
		WorldEditor editor = Workbench.GetModule(WorldEditor);
		if (!editor)
			return;
		string value;
		if (editor.GetCmdLine("-job", value) && value != "")
			m_sJob = value;
		if (editor.GetCmdLine("-size", value) && value != "")
			m_fSize = value.ToFloat();
		if (editor.GetCmdLine("-tile", value) && value != "")
			m_fTile = value.ToFloat();
		if (editor.GetCmdLine("-buildingStep", value) && value != "")
			m_fStep = value.ToFloat();
		if (editor.GetCmdLine("-maxTiles", value) && value != "")
			m_iMaxTiles = value.ToInt();
		if (editor.GetCmdLine("-out", value) && value != "")
			m_sOut = value;
		if (editor.GetCmdLine("-height", value) && value != "")
			m_fCamHeight = value.ToFloat();
		if (editor.GetCmdLine("-fov", value) && value != "")
			m_fFov = value.ToFloat();
	}

	protected void Export(bool fromCommandLine)
	{
		if (m_sJob == "roads")
		{
			ExportRoads(fromCommandLine);
			return;
		}
		if (m_sJob == "satellite")
		{
			ExportSatellite(fromCommandLine);
			return;
		}
		if (m_sJob != "buildings")
		{
			Print("MapExport: job must be buildings, roads, or satellite", LogLevel.ERROR);
			if (fromCommandLine)
				Workbench.Exit(1);
			return;
		}
		ExportBuildings(fromCommandLine);
	}

	protected bool BindWorld()
	{
		m_Editor = Workbench.GetModule(WorldEditor);
		if (!m_Editor)
			return false;
		m_Api = m_Editor.GetApi();
		if (!m_Api)
			return false;
		m_World = m_Api.GetWorld();
		return m_World != null;
	}

	protected bool AddProbe(IEntity e)
	{
		m_iProbeCount++;
		return true;
	}

	protected bool ProbeLoaded()
	{
		m_iProbeCount = 0;
		float inset = m_fSize * 0.2;
		float span = m_fSize * 0.6;
		float half = 100;
		for (int iz = 0; iz < 3; iz++)
		{
			for (int ix = 0; ix < 3; ix++)
			{
				float cx = inset + span * ix / 2;
				float cz = inset + span * iz / 2;
				int before = m_iProbeCount;
				m_World.QueryEntitiesByAABB(Vector(cx - half, -500, cz - half), Vector(cx + half, 3000, cz + half), AddProbe);
				int found = m_iProbeCount - before;
				Print(string.Format("MapExport: probe box %1,%2 has %3 entities", ix, iz, found), LogLevel.NORMAL);
			}
		}
		Print(string.Format("MapExport: probe total %1", m_iProbeCount), LogLevel.NORMAL);
		return m_iProbeCount >= 100;
	}

	protected bool Prepare(bool fromCommandLine)
	{
		if (m_fSize < 1 || m_fTile < 1)
		{
			Print("MapExport: size and tile are not usable", LogLevel.ERROR);
			if (fromCommandLine)
				Workbench.Exit(1);
			return false;
		}
		if (!BindWorld())
		{
			Print("MapExport: no world loaded", LogLevel.ERROR);
			if (fromCommandLine)
				Workbench.Exit(3);
			return false;
		}
		string loaded;
		m_Api.GetWorldPath(loaded);
		Print("MapExport: world " + loaded, LogLevel.NORMAL);
		int editors = m_Api.GetEditorEntityCount();
		Print(string.Format("MapExport: editor entities %1", editors), LogLevel.NORMAL);
		if (!ProbeLoaded())
		{
			Print("MapExport: probe found almost no entities; world is not loaded. Writing nothing.", LogLevel.ERROR);
			if (fromCommandLine)
				Workbench.Exit(3);
			return false;
		}
		FileIO.MakeDirectory(m_sOut);
		return true;
	}

	protected bool WriteJobStatus(string file, string result, int made, int skipped, int remaining)
	{
		FileHandle f = FileIO.OpenFile(m_sOut + "/" + file, FileMode.WRITE);
		if (!f)
			return false;
		f.Write("{\n");
		f.Write(string.Format("  \"result\": \"%1\",\n", result));
		f.Write(string.Format("  \"made\": %1,\n", made));
		f.Write(string.Format("  \"skipped\": %1,\n", skipped));
		f.Write(string.Format("  \"remaining\": %1\n", remaining));
		f.Write("}\n");
		f.Close();
		return true;
	}

	protected void FinishJob(bool fromCommandLine, string file, string result, int made, int skipped, int remaining)
	{
		if (!WriteJobStatus(file, result, made, skipped, remaining))
		{
			Print("MapExport: could not write " + file, LogLevel.ERROR);
			if (fromCommandLine)
				Workbench.Exit(1);
			return;
		}
		Print(string.Format("MapExport: %1", result), LogLevel.NORMAL);
		Print(string.Format("MapExport: made %1, skipped %2, remaining %3", made, skipped, remaining), LogLevel.NORMAL);
		if (!fromCommandLine)
			return;
		if (result == "failed")
			Workbench.Exit(1);
		Workbench.Exit(0);
	}

	protected int TileCount()
	{
		return Math.Ceil(m_fSize / m_fTile);
	}

	protected bool Both(string csvPath)
	{
		if (!FileIO.FileExists(csvPath))
			return false;
		return FileIO.FileExists(csvPath + ".ok");
	}

	protected bool WriteOk(string csvPath)
	{
		FileHandle ok = FileIO.OpenFile(csvPath + ".ok", FileMode.WRITE);
		if (!ok)
			return false;
		ok.Write("ok\n");
		ok.Close();
		return true;
	}

	protected string Q(string s)
	{
		if (!s.Contains(",") && !s.Contains("\"") && !s.Contains("\n") && !s.Contains("\r"))
			return s;
		return "\"" + s.Replace("\"", "\"\"") + "\"";
	}

	protected bool AddEntity(IEntity e)
	{
		m_aFound.Insert(e);
		return true;
	}

	//------------------------------------------------------------------------------------------------
	protected void ExportBuildings(bool fromCommandLine)
	{
		if (m_fStep < 0.5)
		{
			Print("MapExport: buildingStep is not usable", LogLevel.ERROR);
			if (fromCommandLine)
				Workbench.Exit(1);
			return;
		}
		if (!Prepare(fromCommandLine))
			return;
		string folder = m_sOut + "/buildings";
		FileIO.MakeDirectory(folder);
		int n = TileCount();
		int skipped = 0;
		for (int tz = 0; tz < n; tz++)
		{
			for (int tx = 0; tx < n; tx++)
			{
				if (BuildingTileDone(folder, tx, tz))
					skipped++;
			}
		}
		int total = n * n;
		int made = 0;
		bool failed = false;
		for (int tz1 = 0; tz1 < n && !failed; tz1++)
		{
			for (int tx1 = 0; tx1 < n && !failed; tx1++)
			{
				if (BuildingTileDone(folder, tx1, tz1))
					continue;
				if (m_iMaxTiles > 0 && made >= m_iMaxTiles)
				{
					FinishJob(fromCommandLine, "export.status.json", "partial", made, skipped, total - skipped - made);
					return;
				}
				if (!WriteBuildingTile(folder, tx1, tz1))
				{
					failed = true;
					break;
				}
				made++;
				Print(string.Format("MapExport: buildings tile %1,%2", tx1, tz1), LogLevel.NORMAL);
			}
		}
		string result = "done";
		if (failed)
			result = "failed";
		int remaining = total - skipped - made;
		if (!failed && remaining > 0)
			result = "partial";
		FinishJob(fromCommandLine, "export.status.json", result, made, skipped, remaining);
	}

	protected bool BuildingTileDone(string folder, int tx, int tz)
	{
		if (!Both(string.Format("%1/b_%2_%3.csv", folder, tx, tz)))
			return false;
		if (!Both(string.Format("%1/d_%2_%3.csv", folder, tx, tz)))
			return false;
		return Both(string.Format("%1/f_%2_%3.csv", folder, tx, tz));
	}

	protected bool WriteBuildingTile(string folder, int tx, int tz)
	{
		float x0 = tx * m_fTile;
		float z0 = tz * m_fTile;
		m_aFound.Clear();
		m_World.QueryEntitiesByAABB(Vector(x0, -500, z0), Vector(x0 + m_fTile, 3000, z0 + m_fTile), AddEntity);
		string bPath = string.Format("%1/b_%2_%3.csv", folder, tx, tz);
		string dPath = string.Format("%1/d_%2_%3.csv", folder, tx, tz);
		string fPath = string.Format("%1/f_%2_%3.csv", folder, tx, tz);
		FileHandle fb = FileIO.OpenFile(bPath, FileMode.WRITE);
		if (!fb)
			return false;
		FileHandle fd = FileIO.OpenFile(dPath, FileMode.WRITE);
		if (!fd)
		{
			fb.Close();
			return false;
		}
		FileHandle ff = FileIO.OpenFile(fPath, FileMode.WRITE);
		if (!ff)
		{
			fb.Close();
			fd.Close();
			return false;
		}
		fb.Write("id,class,prefab,x,y,z,yaw,pitch,roll,scale,minx,miny,minz,maxx,maxy,maxz,enterable,doors,floors,parts\n");
		fd.Write("id,kind,x,y,z,class\n");
		ff.Write("id,y,samples\n");
		foreach (IEntity e : m_aFound)
		{
			vector origin = e.GetOrigin();
			if (origin[0] < x0 || origin[0] >= x0 + m_fTile || origin[2] < z0 || origin[2] >= z0 + m_fTile)
				continue;
			string prefab = "";
			EntityPrefabData pd = e.GetPrefabData();
			if (pd)
				prefab = pd.GetPrefabName();
			string cls = e.ClassName();
			if (!IsBuilding(e, cls, prefab))
				continue;
			WriteBuilding(e, cls, prefab, fb, fd, ff);
		}
		fb.Close();
		fd.Close();
		ff.Close();
		if (!WriteOk(bPath) || !WriteOk(dPath) || !WriteOk(fPath))
			return false;
		return true;
	}

	protected bool IsBuilding(IEntity e, string cls, string prefab)
	{
		if (cls.Contains("Decal") || cls.Contains("Light") || cls.Contains("Road") || cls.Contains("Probe"))
			return false;
		bool match = cls.Contains("Building");
		if (!match && (prefab.Contains("/Structures/") || prefab.Contains("/Buildings/") || prefab.Contains("/Houses/")))
			match = true;
		if (!match)
			return false;
		vector wmin, wmax;
		e.GetWorldBounds(wmin, wmax);
		float dx = wmax[0] - wmin[0];
		float dz = wmax[2] - wmin[2];
		float dy = wmax[1] - wmin[1];
		if (dx > 400 || dz > 400)
			return false;
		if ((dx < 3 && dz < 3) || dy < 2)
			return false;
		return true;
	}

	protected void WriteBuilding(IEntity e, string cls, string prefab, FileHandle fb, FileHandle fd, FileHandle ff)
	{
		vector origin = e.GetOrigin();
		vector ypr = e.GetYawPitchRoll();
		vector wmin, wmax;
		e.GetWorldBounds(wmin, wmax);
		int xcm = Math.Round(origin[0] * 100);
		int ycm = Math.Round(origin[1] * 100);
		int zcm = Math.Round(origin[2] * 100);
		string id = string.Format("%1_%2_%3", xcm, ycm, zcm);

		ref array<string> kinds = new array<string>();
		ref array<vector> positions = new array<vector>();
		ref array<string> classes = new array<string>();
		ref array<string> parts = new array<string>();
		Collect(e, true, kinds, positions, classes, parts);

		ref array<float> floorY = new array<float>();
		ref array<int> floorN = new array<int>();
		Floors(wmin, wmax, floorY, floorN);

		int doorCount = 0;
		bool enterable = false;
		for (int i = 0; i < kinds.Count(); i++)
		{
			string kind = kinds[i];
			if (kind == "door" || kind == "sliding-door" || kind == "hatch")
			{
				doorCount++;
				enterable = true;
			}
			else if (kind == "ladder")
				enterable = true;
		}
		if (floorY.Count() > 0)
		{
			float lowest = floorY[0];
			for (int f = 1; f < floorY.Count(); f++)
			{
				if (floorY[f] < lowest)
					lowest = floorY[f];
			}
			for (int f2 = 0; f2 < floorY.Count(); f2++)
			{
				if (floorY[f2] >= lowest + 2)
					enterable = true;
			}
		}
		AddGaps(wmin, wmax, kinds, positions, classes);

		int enterFlag = 0;
		if (enterable)
			enterFlag = 1;
		float scale = e.GetScale();
		string line = string.Format("%1,%2,%3,%4,%5,%6,%7,%8,", id, Q(cls), Q(prefab), origin[0], origin[1], origin[2], ypr[0], ypr[1]);
		line = line + string.Format("%1,%2,%3,%4,%5,%6,%7,%8,", ypr[2], scale, wmin[0], wmin[1], wmin[2], wmax[0], wmax[1], wmax[2]);
		line = line + string.Format("%1,%2,%3,", enterFlag, doorCount, floorY.Count());
		line = line + Q(JoinParts(parts)) + "\n";
		fb.Write(line);
		for (int d = 0; d < kinds.Count(); d++)
		{
			vector p = positions[d];
			string dline = string.Format("%1,%2,%3,%4,%5,", id, kinds[d], p[0], p[1], p[2]);
			dline = dline + Q(classes[d]) + "\n";
			fd.Write(dline);
		}
		for (int g = 0; g < floorY.Count(); g++)
			ff.Write(string.Format("%1,%2,%3\n", id, floorY[g], floorN[g]));
	}

	protected string JoinParts(array<string> parts)
	{
		string s = "";
		for (int i = 0; i < parts.Count(); i++)
		{
			if (i > 0)
				s = s + "|";
			s = s + parts[i];
		}
		return s;
	}

	protected bool Listed(array<string> parts, string cls)
	{
		for (int i = 0; i < parts.Count(); i++)
		{
			if (parts[i] == cls)
				return true;
		}
		return false;
	}

	protected string DoorKind(string componentClass, string entityClass)
	{
		if (componentClass.Contains("Hatch") || entityClass.Contains("Hatch"))
			return "hatch";
		if (componentClass.Contains("Sliding") || entityClass.Contains("Sliding"))
			return "sliding-door";
		return "door";
	}

	protected void Collect(IEntity e, bool isRoot, array<string> kinds, array<vector> positions, array<string> classes, array<string> parts)
	{
		string cls = e.ClassName();
		if (!isRoot)
		{
			if (!Listed(parts, cls))
				parts.Insert(cls);
			if (cls.Contains("Ladder"))
			{
				kinds.Insert("ladder");
				positions.Insert(e.GetOrigin());
				classes.Insert(cls);
			}
		}
		BaseDoorComponent door = BaseDoorComponent.Cast(e.FindComponent(BaseDoorComponent));
		if (door)
		{
			string dcls = door.ClassName();
			kinds.Insert(DoorKind(dcls, cls));
			positions.Insert(door.GetDoorPivotPointWS());
			classes.Insert(dcls);
		}
		IEntity child = e.GetChildren();
		while (child)
		{
			Collect(child, false, kinds, positions, classes, parts);
			child = child.GetSibling();
		}
	}

	protected float TraceFrac(vector from, vector to)
	{
		TraceParam p = new TraceParam();
		p.Start = from;
		p.End = to;
		p.Flags = TraceFlags.WORLD | TraceFlags.ENTS;
		p.LayerMask = 0xFFFFFFFF;
		return m_World.TraceMove(p, null);
	}

	protected void AxisSamples(float lo, float hi, array<float> outSamples)
	{
		float width = hi - lo;
		if (width <= m_fStep)
		{
			outSamples.Insert((lo + hi) * 0.5);
			return;
		}
		float v = lo + m_fStep * 0.5;
		while (v < hi)
		{
			outSamples.Insert(v);
			v = v + m_fStep;
		}
	}

	protected void SampleColumn(float x, float z, vector wmin, vector wmax, array<float> hits)
	{
		float top = wmax[1];
		float y = top + 0.5;
		float limit = wmin[1] - 0.5;
		int guard = 0;
		while (y > limit && guard < 24)
		{
			guard++;
			float frac = TraceFrac(Vector(x, y, z), Vector(x, limit, z));
			if (frac >= 0.999)
				break;
			float hitY = y + (limit - y) * frac;
			if (top - hitY > 0.4)
				hits.Insert(hitY);
			float next = hitY - 0.05;
			if (next >= y)
				break;
			y = next;
		}
	}

	protected void Floors(vector wmin, vector wmax, array<float> floorY, array<int> floorN)
	{
		ref array<float> xs = new array<float>();
		ref array<float> zs = new array<float>();
		ref array<float> hits = new array<float>();
		AxisSamples(wmin[0], wmax[0], xs);
		AxisSamples(wmin[2], wmax[2], zs);
		for (int ix = 0; ix < xs.Count(); ix++)
		{
			for (int iz = 0; iz < zs.Count(); iz++)
				SampleColumn(xs[ix], zs[iz], wmin, wmax, hits);
		}
		for (int i = 1; i < hits.Count(); i++)
		{
			float v = hits[i];
			int j = i;
			while (j > 0 && hits[j - 1] > v)
			{
				hits[j] = hits[j - 1];
				j--;
			}
			hits[j] = v;
		}
		int a = 0;
		while (a < hits.Count())
		{
			int b = a + 1;
			while (b < hits.Count() && hits[b] - hits[a] <= 0.5)
				b++;
			int n = b - a;
			if (n >= 3)
			{
				float sum = 0;
				for (int t = a; t < b; t++)
					sum = sum + hits[t];
				floorY.Insert(sum / n);
				floorN.Insert(n);
			}
			a = b;
		}
	}

	protected void AddGaps(vector wmin, vector wmax, array<string> kinds, array<vector> positions, array<string> classes)
	{
		float y = wmin[1] + 1.2;
		if (y > wmax[1] - 0.3)
			y = (wmin[1] + wmax[1]) * 0.5;
		int room = 40;
		room = GapsOnZ(wmin[2], -1, y, wmin, wmax, kinds, positions, classes, room);
		room = GapsOnZ(wmax[2], 1, y, wmin, wmax, kinds, positions, classes, room);
		room = GapsOnX(wmin[0], -1, y, wmin, wmax, kinds, positions, classes, room);
		GapsOnX(wmax[0], 1, y, wmin, wmax, kinds, positions, classes, room);
	}

	protected int GapsOnZ(float wallZ, int outward, float y, vector wmin, vector wmax, array<string> kinds, array<vector> positions, array<string> classes, int room)
	{
		if (room <= 0)
			return 0;
		ref array<float> xs = new array<float>();
		AxisSamples(wmin[0], wmax[0], xs);
		return GapsFromSamples(xs, true, wallZ, outward, y, kinds, positions, classes, room);
	}

	protected int GapsOnX(float wallX, int outward, float y, vector wmin, vector wmax, array<string> kinds, array<vector> positions, array<string> classes, int room)
	{
		if (room <= 0)
			return 0;
		ref array<float> zs = new array<float>();
		AxisSamples(wmin[2], wmax[2], zs);
		return GapsFromSamples(zs, false, wallX, outward, y, kinds, positions, classes, room);
	}

	protected int GapsFromSamples(array<float> along, bool wallIsZ, float wall, int outward, float y, array<string> kinds, array<vector> positions, array<string> classes, int room)
	{
		int n = along.Count();
		if (n == 0 || room <= 0)
			return room;
		ref array<float> travelled = new array<float>();
		travelled.Resize(n);
		float ray = 6;
		for (int i = 0; i < n; i++)
		{
			vector from;
			vector to;
			float outside = wall + outward * 0.25;
			if (wallIsZ)
			{
				from = Vector(along[i], y, outside);
				to = Vector(along[i], y, outside - outward * ray);
			}
			else
			{
				from = Vector(outside, y, along[i]);
				to = Vector(outside - outward * ray, y, along[i]);
			}
			float frac = TraceFrac(from, to);
			float dist = frac * ray;
			if (frac >= 0.999)
				dist = ray;
			travelled[i] = dist;
		}
		for (int s = 0; s < n && room > 0; s++)
		{
			if (travelled[s] <= 2.5)
				continue;
			bool solidNeighbour = false;
			if (s > 0 && travelled[s - 1] <= 1.5)
				solidNeighbour = true;
			if (s + 1 < n && travelled[s + 1] <= 1.5)
				solidNeighbour = true;
			if (!solidNeighbour)
				continue;
			vector at;
			float outsideAt = wall + outward * 0.25;
			if (wallIsZ)
				at = Vector(along[s], y, outsideAt);
			else
				at = Vector(outsideAt, y, along[s]);
			kinds.Insert("gap");
			positions.Insert(at);
			classes.Insert("");
			room--;
		}
		return room;
	}

	//------------------------------------------------------------------------------------------------
	// Roads. The old tool walked top-level entities only. A dirt piece under
	// shape -> generator -> RoadEntity was skipped, Points on that shape were
	// not copied onto the road, and RoadNetworkBridgeComponent was never read.
	// Bridge decks are not RoadEntity. Role words match py/road_cover.py.
	// A bridge with no spline still gets its bounds long-axis. Dirt does not.
	//------------------------------------------------------------------------------------------------
	protected bool HasEither(string s, string a, string b)
	{
		if (s.Contains(a))
			return true;
		return s.Contains(b);
	}

	protected bool DirtMaterial(string s)
	{
		if (HasEither(s, "dirt", "Dirt") || HasEither(s, "forest", "Forest"))
			return true;
		if (HasEither(s, "gravel", "Gravel") || HasEither(s, "soil", "Soil"))
			return true;
		if (HasEither(s, "mud", "Mud") || HasEither(s, "unpaved", "Unpaved"))
			return true;
		return HasEither(s, "earth", "Earth") || HasEither(s, "track", "Track");
	}

	protected bool DirtPrefab(string s)
	{
		if (HasEither(s, "dirt", "Dirt") || HasEither(s, "forest", "Forest"))
			return true;
		return HasEither(s, "gravel", "Gravel") || HasEither(s, "unpaved", "Unpaved");
	}

	protected bool Roadish(string cls, string prefab)
	{
		if (HasEither(cls, "Road", "road"))
			return true;
		return HasEither(prefab, "/Roads/", "/roads/");
	}

	protected string RoleOf(string cls, string prefab, string material)
	{
		if (HasEither(cls, "Bridge", "bridge") || HasEither(prefab, "Bridge", "bridge") || HasEither(material, "Bridge", "bridge"))
			return "bridge";
		if (DirtMaterial(material) || (Roadish(cls, prefab) && DirtPrefab(prefab)))
			return "dirt";
		if (HasEither(material, "trail", "Trail") || HasEither(prefab, "/Trail", "/trail") || HasEither(prefab, "/Paths/", "/paths/"))
			return "path";
		if (Roadish(cls, prefab))
			return "road";
		return "";
	}

	protected string PrefabOfSource(IEntitySource src)
	{
		BaseContainer anc = src.GetAncestor();
		if (!anc)
			return "";
		return anc.GetResourceName();
	}

	protected string GeneratorOf(IEntitySource src)
	{
		int n = src.GetNumChildren();
		for (int i = 0; i < n; i++)
		{
			IEntitySource child = src.GetChild(i);
			if (!child)
				continue;
			string cls = child.GetClassName();
			string prefab = PrefabOfSource(child);
			if (cls.Contains("Generator") || prefab.Contains("Generator"))
			{
				if (prefab == "")
					return cls;
				return prefab;
			}
		}
		return "";
	}

	protected void ClearRoads()
	{
		m_aRId.Clear();
		m_aRRole.Clear();
		m_aRCls.Clear();
		m_aRPrefab.Clear();
		m_aRParent.Clear();
		m_aRMat.Clear();
		m_aRWidth.Clear();
		m_aRType.Clear();
		m_aROrigin.Clear();
		m_aRYaw.Clear();
		m_aRMin.Clear();
		m_aRMax.Clear();
		m_aRTx.Clear();
		m_aRTz.Clear();
		m_aPRoad.Clear();
		m_aPWhich.Clear();
		m_aPI.Clear();
		m_aPPos.Clear();
		m_mSeen.Clear();
		m_iDirt = 0;
		m_iBridge = 0;
		m_iDirtLine = 0;
		m_iBridgeLine = 0;
	}

	protected void AddRoadPoint(int road, string which, vector pos)
	{
		int i = 0;
		for (int p = 0; p < m_aPRoad.Count(); p++)
		{
			if (m_aPRoad[p] == road && m_aPWhich[p] == which)
				i++;
		}
		m_aPRoad.Insert(road);
		m_aPWhich.Insert(which);
		m_aPI.Insert(i);
		m_aPPos.Insert(pos);
	}

	protected int RealPoints(int road)
	{
		int n = 0;
		for (int p = 0; p < m_aPRoad.Count(); p++)
		{
			if (m_aPRoad[p] != road || m_aPWhich[p] == "bounds")
				continue;
			n++;
		}
		return n;
	}

	protected void AddObjectPoints(IEntitySource src, string name, vector mat[4], int road, string which)
	{
		BaseContainerList objs = src.GetObjectArray(name);
		if (!objs)
			return;
		for (int q = 0; q < objs.Count(); q++)
		{
			BaseContainer sp = objs.Get(q);
			if (!sp)
				continue;
			vector local;
			sp.Get("Position", local);
			AddRoadPoint(road, which, local.Multiply4(mat));
		}
	}

	protected void AddFloatPoints(IEntitySource src, string name, vector mat[4], int road, string which)
	{
		array<float> nums = {};
		src.Get(name, nums);
		if (!nums)
			return;
		int n = nums.Count() / 3;
		for (int i = 0; i < n; i++)
		{
			vector local = Vector(nums[i * 3], nums[i * 3 + 1], nums[i * 3 + 2]);
			AddRoadPoint(road, which, local.Multiply4(mat));
		}
	}

	protected void AddBoundsLine(int road, vector wmin, vector wmax)
	{
		float dx = wmax[0] - wmin[0];
		float dz = wmax[2] - wmin[2];
		float y = (wmin[1] + wmax[1]) * 0.5;
		float cx = (wmin[0] + wmax[0]) * 0.5;
		float cz = (wmin[2] + wmax[2]) * 0.5;
		if (dx >= dz)
		{
			AddRoadPoint(road, "bounds", Vector(wmin[0], y, cz));
			AddRoadPoint(road, "bounds", Vector(wmax[0], y, cz));
		}
		else
		{
			AddRoadPoint(road, "bounds", Vector(cx, y, wmin[2]));
			AddRoadPoint(road, "bounds", Vector(cx, y, wmax[2]));
		}
	}

	protected void ClearPull()
	{
		m_bFoundSurface = false;
		m_sPullMat = "";
		m_sPullPrefab = "";
		m_sPullCls = "";
		m_fPullWidth = 0;
		m_iPullType = 0;
	}

	protected void ConsiderSurface(IEntitySource src)
	{
		if (!src || m_bFoundSurface)
			return;
		string cls = src.GetClassName();
		if (!cls.Contains("RoadEntity"))
			return;
		m_bFoundSurface = true;
		m_sPullCls = cls;
		m_sPullPrefab = PrefabOfSource(src);
		string mat;
		src.Get("Material", mat);
		m_sPullMat = mat;
		float width;
		src.Get("Width", width);
		m_fPullWidth = width;
		int rtype;
		src.Get("Type", rtype);
		m_iPullType = rtype;
	}

	protected void FindSurface(IEntitySource src, int depth)
	{
		if (!src || depth > 6 || m_bFoundSurface)
			return;
		int n = src.GetNumChildren();
		for (int i = 0; i < n; i++)
		{
			IEntitySource child = src.GetChild(i);
			ConsiderSurface(child);
			if (!m_bFoundSurface)
				FindSurface(child, depth + 1);
		}
	}

	protected int ShapePointTotal(IEntity ent)
	{
		ShapeEntity shape = ShapeEntity.Cast(ent);
		if (!shape)
			return 0;
		int n = 0;
		array<vector> curve = {};
		shape.GenerateTesselatedShape(curve);
		if (curve)
			n = curve.Count();
		if (n >= 2)
			return n;
		array<vector> pts = {};
		shape.GetPointsPositions(pts);
		if (pts)
			n = n + pts.Count();
		return n;
	}

	protected bool ShapeKeepsLine(IEntitySource src)
	{
		string cls = src.GetClassName();
		if (cls.Contains("Generator"))
			return false;
		if (GeneratorOf(src) != "")
			return true;
		if (HasBridgeComponent(src))
			return true;
		string prefab = PrefabOfSource(src);
		string material;
		src.Get("Material", material);
		if (RoleOf(cls, prefab, material) != "")
			return true;
		ClearPull();
		FindSurface(src, 0);
		return m_bFoundSurface;
	}

	protected bool AncestorOwnsLine(IEntitySource src)
	{
		IEntitySource parent = src.GetParent();
		int guard = 0;
		while (parent && guard < 8)
		{
			IEntity pent = m_Api.SourceToEntity(parent);
			if (pent && ShapePointTotal(pent) >= 2 && ShapeKeepsLine(parent))
				return true;
			parent = parent.GetParent();
			guard++;
		}
		return false;
	}

	protected void AddWorldShapePoints(IEntity ent, int road)
	{
		ShapeEntity shape = ShapeEntity.Cast(ent);
		if (!shape)
			return;
		vector mat[4];
		shape.GetWorldTransform(mat);
		array<vector> curve = {};
		shape.GenerateTesselatedShape(curve);
		if (curve)
		{
			for (int p = 0; p < curve.Count(); p++)
				AddRoadPoint(road, "curve", curve[p].Multiply4(mat));
		}
		if (RealPoints(road) >= 2)
			return;
		array<vector> pts = {};
		shape.GetPointsPositions(pts);
		if (!pts)
			return;
		for (int i = 0; i < pts.Count(); i++)
			AddRoadPoint(road, "points", pts[i].Multiply4(mat));
	}

	protected void AddAncestorShapeLine(IEntitySource src, int road)
	{
		IEntitySource parent = src.GetParent();
		int guard = 0;
		while (parent && guard < 8)
		{
			IEntity pent = m_Api.SourceToEntity(parent);
			if (pent)
				AddWorldShapePoints(pent, road);
			if (RealPoints(road) >= 2)
				return;
			parent = parent.GetParent();
			guard++;
		}
	}

	protected bool HasBridgeComponent(IEntitySource src)
	{
		int n = src.GetComponentCount();
		for (int i = 0; i < n; i++)
		{
			IEntityComponentSource comp = src.GetComponent(i);
			if (!comp)
				continue;
			if (comp.GetClassName().Contains("RoadNetworkBridge"))
				return true;
		}
		return false;
	}

	protected float Spread(array<vector> pts, vector origin)
	{
		if (!pts || pts.Count() == 0)
			return 0;
		float sum = 0;
		for (int i = 0; i < pts.Count(); i++)
		{
			vector d = pts[i] - origin;
			sum = sum + Math.Sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]);
		}
		return sum / pts.Count();
	}

	protected bool ReadPointName(IEntityComponentSource comp, string name, vector mat[4], vector origin, int road)
	{
		array<vector> localPts = {};
		BaseContainerList objs = comp.GetObjectArray(name);
		if (objs)
		{
			for (int q = 0; q < objs.Count(); q++)
			{
				BaseContainer sp = objs.Get(q);
				if (!sp)
					continue;
				vector local;
				sp.Get("Position", local);
				localPts.Insert(local);
			}
		}
		if (localPts.Count() < 2)
		{
			array<float> nums = {};
			comp.Get(name, nums);
			if (nums && nums.Count() >= 6)
			{
				localPts.Clear();
				int n = nums.Count() / 3;
				for (int i = 0; i < n; i++)
					localPts.Insert(Vector(nums[i * 3], nums[i * 3 + 1], nums[i * 3 + 2]));
			}
		}
		if (localPts.Count() < 2)
			return false;
		array<vector> worldPts = {};
		for (int j = 0; j < localPts.Count(); j++)
			worldPts.Insert(localPts[j].Multiply4(mat));
		bool useRaw = Spread(localPts, origin) < Spread(worldPts, origin);
		for (int k = 0; k < localPts.Count(); k++)
		{
			vector pos = localPts[k];
			if (!useRaw)
				pos = localPts[k].Multiply4(mat);
			AddRoadPoint(road, "bridge", pos);
		}
		return true;
	}

	protected void AddBridgeComponentPoints(IEntitySource src, vector mat[4], vector origin, int road)
	{
		int n = src.GetComponentCount();
		for (int i = 0; i < n; i++)
		{
			IEntityComponentSource comp = src.GetComponent(i);
			if (!comp)
				continue;
			if (!comp.GetClassName().Contains("RoadNetworkBridge"))
				continue;
			if (ReadPointName(comp, "Points", mat, origin, road))
				return;
			if (ReadPointName(comp, "SplinePoints", mat, origin, road))
				return;
			if (ReadPointName(comp, "m_aPoints", mat, origin, road))
				return;
			if (ReadPointName(comp, "LinePoints", mat, origin, road))
				return;
			if (ReadPointName(comp, "BridgePoints", mat, origin, road))
				return;
		}
	}

	protected int BoundsPoints(int road)
	{
		int n = 0;
		for (int p = 0; p < m_aPRoad.Count(); p++)
		{
			if (m_aPRoad[p] == road && m_aPWhich[p] == "bounds")
				n++;
		}
		return n;
	}

	protected void StripPoints(int road)
	{
		for (int p = m_aPRoad.Count() - 1; p >= 0; p--)
		{
			if (m_aPRoad[p] != road)
				continue;
			m_aPRoad.RemoveOrdered(p);
			m_aPWhich.RemoveOrdered(p);
			m_aPI.RemoveOrdered(p);
			m_aPPos.RemoveOrdered(p);
		}
	}

	protected void RememberRoad(IEntitySource src, string parentCls)
	{
		string cls = src.GetClassName();
		if (cls.Contains("Generator"))
			return;
		string prefab = PrefabOfSource(src);
		string material;
		src.Get("Material", material);
		string role = RoleOf(cls, prefab, material);
		string gen = GeneratorOf(src);
		if (role == "" && gen != "")
			role = RoleOf("", gen, material);
		if (role == "" && gen != "")
			role = "road";
		if (cls.Contains("RoadEntity") && AncestorOwnsLine(src))
			return;
		ClearPull();
		if (!cls.Contains("RoadEntity"))
		{
			FindSurface(src, 0);
			if (m_bFoundSurface)
			{
				string pulled = RoleOf(m_sPullCls, m_sPullPrefab, m_sPullMat);
				if (pulled == "dirt" || pulled == "bridge" || pulled == "path")
					role = pulled;
				else if ((role == "" || role == "road") && pulled != "")
					role = pulled;
				if (material == "")
					material = m_sPullMat;
				if (prefab == "")
					prefab = m_sPullPrefab;
			}
		}
		if (HasBridgeComponent(src) && role != "dirt")
			role = "bridge";
		if (role == "")
			return;
		IEntity ent = m_Api.SourceToEntity(src);
		if (!ent)
			return;
		vector origin = ent.GetOrigin();
		if (origin[0] < 0 || origin[2] < 0 || origin[0] >= m_fSize || origin[2] >= m_fSize)
			return;
		int xcm = Math.Round(origin[0] * 100);
		int ycm = Math.Round(origin[1] * 100);
		int zcm = Math.Round(origin[2] * 100);
		string key = string.Format("%1|%2|%3|%4|", cls, prefab, xcm, ycm);
		key = key + zcm.ToString();
		if (m_mSeen.Contains(key))
			return;

		vector wmin, wmax;
		ent.GetWorldBounds(wmin, wmax);
		vector ypr = ent.GetYawPitchRoll();
		float width;
		src.Get("Width", width);
		int rtype;
		src.Get("Type", rtype);
		if (m_bFoundSurface && width == 0)
			width = m_fPullWidth;
		int road = m_aRId.Count();
		vector mat[4];
		ent.GetWorldTransform(mat);
		AddWorldShapePoints(ent, road);
		int shaped = RealPoints(road);
		AddObjectPoints(src, "SplinePoints", mat, road, "spline");
		if (shaped < 2)
			AddObjectPoints(src, "Points", mat, road, "points");
		if (RealPoints(road) < 2)
			AddFloatPoints(src, "SplinePoints", mat, road, "spline");
		if (RealPoints(road) < 2)
			AddFloatPoints(src, "Points", mat, road, "points");
		if (RealPoints(road) < 2)
			AddAncestorShapeLine(src, road);
		if (RealPoints(road) < 2)
			AddBridgeComponentPoints(src, mat, origin, road);
		if (RealPoints(road) < 2 && role == "bridge")
			AddBoundsLine(road, wmin, wmax);
		bool bareDirt = role == "dirt" && cls.Contains("RoadEntity");
		if (RealPoints(road) < 2 && role != "bridge" && !bareDirt)
		{
			StripPoints(road);
			return;
		}

		m_mSeen.Set(key, 1);
		string id = string.Format("%1_%2_%3_%4", xcm, ycm, zcm, road);
		m_aRId.Insert(id);
		m_aRRole.Insert(role);
		m_aRCls.Insert(cls);
		m_aRPrefab.Insert(prefab);
		m_aRParent.Insert(parentCls);
		m_aRMat.Insert(material);
		m_aRWidth.Insert(width);
		m_aRType.Insert(rtype);
		m_aROrigin.Insert(origin);
		m_aRYaw.Insert(ypr[0]);
		m_aRMin.Insert(wmin);
		m_aRMax.Insert(wmax);
		m_aRTx.Insert(Math.Floor(origin[0] / m_fTile));
		m_aRTz.Insert(Math.Floor(origin[2] / m_fTile));
		if (role == "dirt")
		{
			m_iDirt++;
			if (RealPoints(road) >= 2)
				m_iDirtLine++;
		}
		if (role == "bridge")
		{
			m_iBridge++;
			if (RealPoints(road) >= 2 || BoundsPoints(road) >= 2)
				m_iBridgeLine++;
		}
	}

	protected void WalkRoads(IEntitySource src, string parentCls)
	{
		if (!src)
			return;
		RememberRoad(src, parentCls);
		string cls = src.GetClassName();
		int n = src.GetNumChildren();
		for (int i = 0; i < n; i++)
			WalkRoads(src.GetChild(i), cls);
	}

	protected bool RoadTileDone(string folder, int tx, int tz)
	{
		if (!Both(string.Format("%1/n_%2_%3.csv", folder, tx, tz)))
			return false;
		return Both(string.Format("%1/p_%2_%3.csv", folder, tx, tz));
	}

	protected void ExportRoads(bool fromCommandLine)
	{
		if (!Prepare(fromCommandLine))
			return;
		string folder = m_sOut + "/roads";
		FileIO.MakeDirectory(folder);
		ClearRoads();
		int editors = m_Api.GetEditorEntityCount();
		for (int i = 0; i < editors; i++)
			WalkRoads(m_Api.GetEditorEntity(i), "");
		Print(string.Format("MapExport: dirt %1 with a line %2", m_iDirt, m_iDirtLine), LogLevel.NORMAL);
		Print(string.Format("MapExport: bridges %1 with a line %2", m_iBridge, m_iBridgeLine), LogLevel.NORMAL);
		Print(string.Format("MapExport: road pieces %1, points %2", m_aRId.Count(), m_aPPos.Count()), LogLevel.NORMAL);

		int n = TileCount();
		int skipped = 0;
		for (int tz = 0; tz < n; tz++)
		{
			for (int tx = 0; tx < n; tx++)
			{
				if (RoadTileDone(folder, tx, tz))
					skipped++;
			}
		}
		int total = n * n;
		int made = 0;
		bool failed = false;
		for (int tz1 = 0; tz1 < n && !failed; tz1++)
		{
			for (int tx1 = 0; tx1 < n && !failed; tx1++)
			{
				if (RoadTileDone(folder, tx1, tz1))
					continue;
				if (m_iMaxTiles > 0 && made >= m_iMaxTiles)
				{
					FinishJob(fromCommandLine, "roads.status.json", "partial", made, skipped, total - skipped - made);
					return;
				}
				if (!WriteRoadTile(folder, tx1, tz1))
				{
					failed = true;
					break;
				}
				made++;
			}
		}
		string result = "done";
		if (failed)
			result = "failed";
		int remaining = total - skipped - made;
		if (!failed && remaining > 0)
			result = "partial";
		FinishJob(fromCommandLine, "roads.status.json", result, made, skipped, remaining);
	}

	protected bool WriteRoadTile(string folder, int tx, int tz)
	{
		string nPath = string.Format("%1/n_%2_%3.csv", folder, tx, tz);
		string pPath = string.Format("%1/p_%2_%3.csv", folder, tx, tz);
		FileHandle fn = FileIO.OpenFile(nPath, FileMode.WRITE);
		if (!fn)
			return false;
		FileHandle fp = FileIO.OpenFile(pPath, FileMode.WRITE);
		if (!fp)
		{
			fn.Close();
			return false;
		}
		fn.Write("id,role,class,prefab,parent,material,width,type,x,y,z,yaw,minx,miny,minz,maxx,maxy,maxz\n");
		fp.Write("id,which,i,x,y,z\n");
		for (int r = 0; r < m_aRId.Count(); r++)
		{
			if (m_aRTx[r] != tx || m_aRTz[r] != tz)
				continue;
			vector o = m_aROrigin[r];
			vector wmin = m_aRMin[r];
			vector wmax = m_aRMax[r];
			string line = string.Format("%1,%2,%3,%4,%5,%6,%7,%8,", m_aRId[r], m_aRRole[r], Q(m_aRCls[r]), Q(m_aRPrefab[r]), Q(m_aRParent[r]), Q(m_aRMat[r]), m_aRWidth[r], m_aRType[r]);
			line = line + string.Format("%1,%2,%3,%4,%5,%6,%7,%8,", o[0], o[1], o[2], m_aRYaw[r], wmin[0], wmin[1], wmin[2], wmax[0]);
			line = line + string.Format("%1,%2\n", wmax[1], wmax[2]);
			fn.Write(line);
			for (int p = 0; p < m_aPRoad.Count(); p++)
			{
				if (m_aPRoad[p] != r)
					continue;
				vector pos = m_aPPos[p];
				fp.Write(string.Format("%1,%2,%3,%4,%5,%6\n", m_aRId[r], m_aPWhich[p], m_aPI[p], pos[0], pos[1], pos[2]));
			}
		}
		fn.Close();
		fp.Close();
		if (!WriteOk(nPath) || !WriteOk(pPath))
			return false;
		return true;
	}

	//------------------------------------------------------------------------------------------------
	protected void ExportSatellite(bool fromCommandLine)
	{
		if (!Prepare(fromCommandLine))
			return;
		string folder = m_sOut + "/satellite";
		FileIO.MakeDirectory(folder);
		float fov = m_fFov;
		if (fov < 1)
			fov = 15;
		float camH = m_fCamHeight;
		if (camH < 1)
		{
			float tan = Math.Tan(fov * 0.5 * Math.PI2 / 360);
			if (tan < 0.02)
				tan = 0.02;
			camH = (m_fTile * 0.5) / tan;
		}
		Print(string.Format("MapExport: camera height %1 m, fov %2", camH, fov), LogLevel.NORMAL);
		Print("MapExport: set the editor camera to that fov and a far plane above the height", LogLevel.NORMAL);

		int n = TileCount();
		int skipped = 0;
		for (int tz = 0; tz < n; tz++)
		{
			for (int tx = 0; tx < n; tx++)
			{
				if (FileIO.FileExists(string.Format("%1/s_%2_%3.txt.ok", folder, tx, tz)))
					skipped++;
			}
		}
		int total = n * n;
		int made = 0;
		bool failed = false;
		for (int tz1 = 0; tz1 < n && !failed; tz1++)
		{
			for (int tx1 = 0; tx1 < n && !failed; tx1++)
			{
				string okPath = string.Format("%1/s_%2_%3.txt.ok", folder, tx1, tz1);
				if (FileIO.FileExists(okPath))
					continue;
				if (m_iMaxTiles > 0 && made >= m_iMaxTiles)
				{
					FinishJob(fromCommandLine, "satellite.status.json", "partial", made, skipped, total - skipped - made);
					return;
				}
				if (!WriteShot(folder, tx1, tz1, camH, fov))
				{
					failed = true;
					break;
				}
				made++;
			}
		}
		string result = "done";
		if (failed)
			result = "failed";
		int remaining = total - skipped - made;
		if (!failed && remaining > 0)
			result = "partial";
		FinishJob(fromCommandLine, "satellite.status.json", result, made, skipped, remaining);
	}

	protected bool WriteShot(string folder, int tx, int tz, float camH, float fov)
	{
		float x0 = tx * m_fTile;
		float z0 = tz * m_fTile;
		float x1 = x0 + m_fTile;
		float z1 = z0 + m_fTile;
		vector cam = Vector((x0 + x1) * 0.5, camH, (z0 + z1) * 0.5);
		m_Api.SetCamera(cam, Vector(0, -90, 0));
		Sleep(400);
		string shot = string.Format("s_%1_%2", tx, tz);
		System.MakeScreenshot(shot);
		string txt = string.Format("%1/%2.txt", folder, shot);
		FileHandle f = FileIO.OpenFile(txt, FileMode.WRITE);
		if (!f)
			return false;
		f.Write("x0,z0,x1,z1,camera,fov,file\n");
		string row = string.Format("%1,%2,%3,%4,%5,%6,", x0, z0, x1, z1, camH, fov);
		row = row + shot + "\n";
		f.Write(row);
		f.Close();
		return WriteOk(txt);
	}
}
