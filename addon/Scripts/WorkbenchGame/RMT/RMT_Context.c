// Shared state for one command-line run: the loaded world, the output folder, and the chunk grid.
// Everything is written under $profile: only; any other path makes Workbench pop a modal
// "Script Authorization Required" dialog that stalls an unattended run.
class RMT_Context
{
	string m_sJob;
	string m_sOut;          // $profile:... run folder
	string m_sWorld;
	WorldEditor m_Editor;
	WorldEditorAPI m_Api;
	BaseWorld m_World;

	vector m_vMin;          // terrain bounds
	vector m_vMax;
	float m_fTile = 500;    // chunk size in metres
	int m_iCols;            // chunks along x
	int m_iRows;            // chunks along z
	int m_iRegionX0;        // chunk region to export (inclusive); -1 = to the end
	int m_iRegionZ0;
	int m_iRegionX1 = -1;
	int m_iRegionZ1 = -1;
	int m_iMaxChunks;       // 0 = no limit (for tests)

	protected ref array<IEntity> m_aFound = {};

	//------------------------------------------------------------------------------------------------
	static void Say(string msg)
	{
		Print("RMT|" + msg, LogLevel.NORMAL);
	}

	//------------------------------------------------------------------------------------------------
	string Arg(string name, string fallback = "")
	{
		string value;
		if (m_Editor.GetCmdLine(name, value) && value != "")
			return value;
		return fallback;
	}

	//------------------------------------------------------------------------------------------------
	// Creates each folder of a "$profile:a/b/c" path in turn (MakeDirectory is not recursive).
	static void MakeDirs(string path)
	{
		array<string> parts = {};
		path.Split("/", parts, true);
		string built = "";
		foreach (int i, string part : parts)
		{
			if (i == 0)
				built = part;
			else
				built = built + "/" + part;
			FileIO.MakeDirectory(built);
		}
	}

	//------------------------------------------------------------------------------------------------
	bool Init(WorldEditor editor)
	{
		m_Editor = editor;
		m_sJob = Arg("-rmtJob");
		m_sOut = Arg("-rmtOut");
		m_sWorld = Arg("-rmtWorld");
		m_fTile = Arg("-rmtTile", "500").ToFloat();
		m_iMaxChunks = Arg("-rmtMaxChunks", "0").ToInt();
		string region = Arg("-rmtRegion");
		if (region != "")
		{
			array<string> r = {};
			region.Split(",", r, true);
			if (r.Count() == 4)
			{
				m_iRegionX0 = r[0].ToInt();
				m_iRegionZ0 = r[1].ToInt();
				m_iRegionX1 = r[2].ToInt();
				m_iRegionZ1 = r[3].ToInt();
			}
		}
		return m_sJob != "" && m_sOut != "" && m_fTile >= 10;
	}

	//------------------------------------------------------------------------------------------------
	// Loads the world and reads its terrain bounds. False if it did not load.
	bool OpenWorld()
	{
		if (m_sWorld == "")
			return false;
		float t0 = System.GetTickCount();
		bool opened = m_Editor.SetOpenedResource(m_sWorld);
		Say(string.Format("opened|%1|ms=%2", opened, System.GetTickCount() - t0));
		m_Api = m_Editor.GetApi();
		if (!m_Api)
			return false;
		m_World = m_Api.GetWorld();
		if (!m_World || m_Api.GetEditorEntityCount() < 1)
			return false;
		if (!m_Editor.GetTerrainBounds(m_vMin, m_vMax))
		{
			Say("no terrain bounds");
			return false;
		}
		m_iCols = Math.Ceil((m_vMax[0] - m_vMin[0]) / m_fTile);
		m_iRows = Math.Ceil((m_vMax[2] - m_vMin[2]) / m_fTile);
		Say(string.Format("world|min=%1|max=%2|chunks=%3x%4|tile=%5", m_vMin, m_vMax, m_iCols, m_iRows, m_fTile));
		return m_iCols > 0 && m_iRows > 0;
	}

	//------------------------------------------------------------------------------------------------
	bool InRegion(int tx, int tz)
	{
		if (tx < m_iRegionX0 || tz < m_iRegionZ0)
			return false;
		if (m_iRegionX1 >= 0 && tx > m_iRegionX1)
			return false;
		if (m_iRegionZ1 >= 0 && tz > m_iRegionZ1)
			return false;
		return true;
	}

	float ChunkX(int tx) { return m_vMin[0] + tx * m_fTile; }
	float ChunkZ(int tz) { return m_vMin[2] + tz * m_fTile; }

	//------------------------------------------------------------------------------------------------
	string ChunkPath(string folder, string prefix, int tx, int tz)
	{
		return string.Format("%1/%2/%3_%4_%5.csv", m_sOut, folder, prefix, tx, tz);
	}

	//------------------------------------------------------------------------------------------------
	// A chunk is finished only when its .ok marker exists; the marker is written after the file is closed.
	bool ChunkDone(string path)
	{
		return FileIO.FileExists(path) && FileIO.FileExists(path + ".ok");
	}

	//------------------------------------------------------------------------------------------------
	bool MarkOk(string path)
	{
		FileHandle ok = FileIO.OpenFile(path + ".ok", FileMode.WRITE);
		if (!ok)
			return false;
		ok.WriteLine("ok");
		ok.Close();
		return true;
	}

	//------------------------------------------------------------------------------------------------
	// Writes <out>/<job>.status.json. rmt.py deletes it before every launch, so it is never stale.
	// The contract (the same for the game-side jobs, see RMT_Status): done = every output the job claims exists, is not
	// empty and holds its rows; partial = a declared incomplete output, still usable, with remaining > 0 saying how much
	// is missing; failed = do not bake it and run it again, with reason saying why.
	// extra: more JSON members, each already formatted as a line ("  \"k\": 1,").
	bool WriteStatus(string job, string result, int made, int skipped, int remaining, int items, float ms, string reason = "", string extra = "")
	{
		FileHandle f = FileIO.OpenFile(string.Format("%1/%2.status.json", m_sOut, job), FileMode.WRITE);
		if (!f)
			return false;
		string why = reason;
		why.Replace("\\", "\\\\");
		why.Replace("\"", "\\\"");
		f.WriteLine("{");
		f.WriteLine(string.Format("  \"job\": \"%1\",", job));
		f.WriteLine(string.Format("  \"result\": \"%1\",", result));
		f.WriteLine(string.Format("  \"made\": %1,", made));
		f.WriteLine(string.Format("  \"skipped\": %1,", skipped));
		f.WriteLine(string.Format("  \"remaining\": %1,", remaining));
		f.WriteLine(string.Format("  \"items\": %1,", items));
		if (extra != "")
			f.WriteLine(extra);
		f.WriteLine(string.Format("  \"reason\": \"%1\",", why));
		f.WriteLine(string.Format("  \"ms\": %1", ms));
		f.WriteLine("}");
		f.Close();
		if (result != "done")
			Say(string.Format("status|%1|%2|%3", job, result, reason));
		return true;
	}

	//------------------------------------------------------------------------------------------------
	protected bool AddEntity(IEntity e)
	{
		m_aFound.Insert(e);
		return true;
	}

	//------------------------------------------------------------------------------------------------
	// Every entity whose box overlaps the area, from well below the sea floor to well above the peaks.
	array<IEntity> Query(float x0, float z0, float x1, float z1)
	{
		m_aFound.Clear();
		m_World.QueryEntitiesByAABB(Vector(x0, m_vMin[1] - 100, z0), Vector(x1, m_vMax[1] + 1000, z1), AddEntity);
		return m_aFound;
	}

	//------------------------------------------------------------------------------------------------
	static string PrefabOf(IEntity e)
	{
		EntityPrefabData pd = e.GetPrefabData();
		if (!pd)
			return "";
		return pd.GetPrefabName();
	}

	//------------------------------------------------------------------------------------------------
	// Engine helpers, not map objects, left out of the entities and surface exports ON PURPOSE (each listed here):
	//   DecalEntity, LightEntity, GameEnvironmentProbeEntity, ProbeVolume, SCR_PrefabSpawnPoint, EntityEditIcon: no shape
	//   RoadEntity: exported by the roads job
	//   PowerlineEntity: the cables between poles; the poles are entities of their own and are kept, and the lines
	//     themselves come from the mapdata job (BI's Geometry2D export)
	//   the terrain, the ocean, lakes and rivers (Water() below): they are the ground and the water, not objects on it
	// Size is not a reason: a long wall, a bridge or a sea wall is kept however long it is.
	static bool Skippable(IEntity e)
	{
		string cls = e.ClassName();
		if (cls == "DecalEntity" || cls == "LightEntity" || cls == "GameEnvironmentProbeEntity" || cls == "ProbeVolume"
			|| cls == "RoadEntity" || cls == "PowerlineEntity" || cls == "SCR_PrefabSpawnPoint" || cls == "EntityEditIcon")
			return true;
		return Water(e) || cls.Contains("Terrain");
	}

	//------------------------------------------------------------------------------------------------
	// The sea, a lake or a river: by class (OceanEntity, LakeEntity, RiverEntity...) or by a water prefab folder.
	static bool Water(IEntity e)
	{
		string cls = e.ClassName();
		if (cls.Contains("Ocean") || cls.Contains("Lake") || cls.Contains("River"))
			return true;
		string prefab = PrefabOf(e);
		return prefab.Contains("/WEGenerators/Water/") || prefab.Contains("/Water/Lake") || prefab.Contains("/Water/River") || prefab.Contains("/Water/Ocean");
	}

	//------------------------------------------------------------------------------------------------
	// Standing vegetation, by prefab folder (the same rule as rmtlib/foliage.py standing_plant) or class: trees,
	// bushes and their destructible versions, whatever entity class they are.
	static bool Vegetation(IEntity e)
	{
		string prefab = PrefabOf(e);
		if (prefab.Contains("/Vegetation/Tree/") || prefab.Contains("/Vegetation/Bush/") || prefab.Contains("/Vegetation/Trees/") || prefab.Contains("/Vegetation/Bushes/"))
			return true;
		string cls = e.ClassName();
		return cls == "Tree" || cls == "Bush" || cls.Contains("TreeEntity") || cls.Contains("BushEntity");
	}

	//------------------------------------------------------------------------------------------------
	// A building: by class, or by the folders the game keeps houses, halls and towers in (walls and fences are not
	// buildings: the baker draws them itself).
	static const ref array<string> BUILDING_FOLDERS = {"/Houses/", "/Ruins/", "/Services/", "/Commercial/Pubs/",
		"/Commercial/Shops/", "/Cultural/Churches/", "/Cultural/Chapels/", "/Cultural/Castles/", "/Agriculture/Barn",
		"/Agriculture/CowShed", "/Agriculture/Hayloft", "/Agriculture/Greenhouse", "/Airport/ControlTower",
		"/Airport/Hangar", "/Military/Bunkers/", "/Industrial/Sheds/", "/Industrial/Garages/", "/Recreation/Houses/"};
	static bool Building(IEntity e)
	{
		if (e.ClassName().Contains("Building"))
			return true;
		string prefab = PrefabOf(e);
		if (!prefab.Contains("/Structures/") || prefab.Contains("/Walls/") || prefab.Contains("/BuildingParts/") || prefab.Contains("/Signs/"))
			return false;
		foreach (string folder : BUILDING_FOLDERS)
		{
			if (prefab.Contains(folder))
				return true;
		}
		return false;
	}

	//------------------------------------------------------------------------------------------------
	// Every entity whose own box overlaps the area, objects reaching in from far outside it included (a long wall, a
	// bridge or a sea wall whose origin is hundreds of metres away). Objects up to PAD m across are found by a query
	// padded by PAD; bigger ones come from a list of every object over PAD m across, made once for the whole world.
	static const float PAD = 50;
	protected ref array<IEntity> m_aLarge;
	array<IEntity> QueryOverlapping(float x0, float z0, float x1, float z1)
	{
		if (!m_aLarge)
		{
			m_aLarge = {};
			foreach (IEntity big : Query(m_vMin[0] - PAD, m_vMin[2] - PAD, m_vMax[0] + PAD, m_vMax[2] + PAD))
			{
				vector bmin, bmax;
				big.GetWorldBounds(bmin, bmax);
				if (bmax[0] - bmin[0] > PAD || bmax[2] - bmin[2] > PAD)
					m_aLarge.Insert(big);
			}
			Say(string.Format("query|objects over %1 m across=%2", PAD, m_aLarge.Count()));
		}
		array<IEntity> found = {};
		set<IEntity> seen = new set<IEntity>();
		array<IEntity> candidates = {};
		candidates.Copy(Query(x0 - PAD, z0 - PAD, x1 + PAD, z1 + PAD));
		candidates.InsertAll(m_aLarge);
		foreach (IEntity e : candidates)
		{
			if (!e || seen.Contains(e))
				continue;
			vector wmin, wmax;
			e.GetWorldBounds(wmin, wmax);
			if (wmax[0] < x0 || wmin[0] > x1 || wmax[2] < z0 || wmin[2] > z1)
				continue;
			seen.Insert(e);
			found.Insert(e);
		}
		return found;
	}

	//------------------------------------------------------------------------------------------------
	// CSV quoting for text columns.
	static string Q(string s)
	{
		if (!s.Contains(",") && !s.Contains("\"") && !s.Contains("\n") && !s.Contains("\r"))
			return s;
		string t = s;
		t.Replace("\"", "\"\"");
		return "\"" + t + "\"";
	}
}

//------------------------------------------------------------------------------------------------
// Base for the jobs that walk the chunk grid. A subclass writes one chunk in WriteChunk.
class RMT_ChunkJob
{
	protected RMT_Context m_Ctx;
	protected string m_sName;    // job name, also the status file name
	protected string m_sFolder;  // sub-folder of the run folder
	protected string m_sPrefix;  // file prefix, e.g. "t" for t_3_7.csv
	protected int m_iItems;

	//------------------------------------------------------------------------------------------------
	void RMT_ChunkJob(RMT_Context ctx, string name, string folder, string prefix)
	{
		m_Ctx = ctx;
		m_sName = name;
		m_sFolder = folder;
		m_sPrefix = prefix;
	}

	//------------------------------------------------------------------------------------------------
	// Returns false if the chunk could not be written. Adds to m_iItems.
	protected bool WriteChunk(int tx, int tz, string path)
	{
		return false;
	}

	//------------------------------------------------------------------------------------------------
	// 0 done, 1 failed. "partial" (a test limit was hit) also returns 0.
	int Run()
	{
		float t0 = System.GetTickCount();
		RMT_Context.MakeDirs(m_Ctx.m_sOut + "/" + m_sFolder);
		int total = 0;
		int skipped = 0;
		for (int tz = 0; tz < m_Ctx.m_iRows; tz++)
		{
			for (int tx = 0; tx < m_Ctx.m_iCols; tx++)
			{
				if (!m_Ctx.InRegion(tx, tz))
					continue;
				total++;
				if (m_Ctx.ChunkDone(m_Ctx.ChunkPath(m_sFolder, m_sPrefix, tx, tz)))
					skipped++;
			}
		}
		RMT_Context.Say(string.Format("job|%1|chunks=%2|done_before=%3", m_sName, total, skipped));
		int made = 0;
		for (int tz1 = 0; tz1 < m_Ctx.m_iRows; tz1++)
		{
			for (int tx1 = 0; tx1 < m_Ctx.m_iCols; tx1++)
			{
				if (!m_Ctx.InRegion(tx1, tz1))
					continue;
				string path = m_Ctx.ChunkPath(m_sFolder, m_sPrefix, tx1, tz1);
				if (m_Ctx.ChunkDone(path))
					continue;
				if (m_Ctx.m_iMaxChunks > 0 && made >= m_Ctx.m_iMaxChunks)
				{
					m_Ctx.WriteStatus(m_sName, "partial", made, skipped, total - skipped - made, m_iItems, System.GetTickCount() - t0, "stopped at the -rmtMaxChunks test limit");
					return 0;
				}
				float c0 = System.GetTickCount();
				int before = m_iItems;
				if (!WriteChunk(tx1, tz1, path) || !m_Ctx.MarkOk(path))
				{
					RMT_Context.Say(string.Format("error|%1|chunk %2,%3 not written", m_sName, tx1, tz1));
					m_Ctx.WriteStatus(m_sName, "failed", made, skipped, total - skipped - made, m_iItems, System.GetTickCount() - t0, string.Format("chunk %1,%2 not written", tx1, tz1));
					return 1;
				}
				made++;
				RMT_Context.Say(string.Format("chunk|%1|%2|%3|items=%4|ms=%5|left=%6", m_sName, tx1, tz1, m_iItems - before, System.GetTickCount() - c0, total - skipped - made));
			}
		}
		m_Ctx.WriteStatus(m_sName, "done", made, skipped, 0, m_iItems, System.GetTickCount() - t0);
		return 0;
	}
}
