// Reforger Map Tools: command-line export plugin. rmt.py starts Workbench with
//   -wbModule=WorldEditor -plugin=RMT_ExportPlugin -rmtJob=<job>[,<job>...] -rmtOut=$profile:<folder>
//   [-rmtWorld=<world .ent>] [-rmtTile=500] [-rmtStep=<m>] [-rmtRegion=tx0,tz0,tx1,tz1] [-rmtMaxChunks=N]
// Jobs: worlds (alone), or any of probe, mapdata, roads, names, entities, terrain, surface, foliagetrace, ballistics - run one after
// another on a single load of the world. Each writes <job>.status.json when it finishes, so after a crash rmt.py
// relaunches with only the jobs still to do (and the chunk jobs skip their finished chunks).
// The satellite pictures are taken in the game, not here (command-line Workbench does not draw the world).
// Lines meant for rmt.py start with "RMT|" in console.log. Exit codes: 0 done, 1 a job failed, 2 bad arguments,
// 3 world did not load.

[WorkbenchPluginAttribute(name: "RMT Export", description: "Reforger Map Tools command-line export", wbModules: {"WorldEditor"}, awesomeFontCode: 0xf279)]
class RMT_ExportPlugin : WorkbenchPlugin
{
	protected ref RMT_Context m_Ctx;
	protected ref array<string> m_aWorlds = {};

	//------------------------------------------------------------------------------------------------
	protected void Finish(int code, string msg)
	{
		RMT_Context.Say(string.Format("exit|%1|%2", code, msg));
		Workbench.Exit(code);
	}

	//------------------------------------------------------------------------------------------------
	override void RunCommandline()
	{
		WorldEditor we = Workbench.GetModule(WorldEditor);
		if (!we)
		{
			Finish(2, "no WorldEditor module");
			return;
		}
		m_Ctx = new RMT_Context();
		if (!m_Ctx.Init(we))
		{
			Finish(2, "need -rmtJob and -rmtOut (and -rmtTile >= 10)");
			return;
		}
		RMT_Context.Say(string.Format("start|job=%1|out=%2|world=%3", m_Ctx.m_sJob, m_Ctx.m_sOut, m_Ctx.m_sWorld));
		RMT_Context.MakeDirs(m_Ctx.m_sOut);

		if (m_Ctx.m_sJob == "worlds")
		{
			Finish(JobWorlds(), "worlds");
			return;
		}
		array<string> jobs = {};
		m_Ctx.m_sJob.Split(",", jobs, true);
		foreach (string job : jobs)
		{
			if (job != "probe" && job != "mapdata" && job != "roads" && job != "names" && job != "entities" && job != "terrain" && job != "surface" && job != "foliagetrace" && job != "ballistics")
			{
				Finish(2, "unknown job " + job);
				return;
			}
		}
		if (!m_Ctx.OpenWorld())
		{
			Finish(3, "world did not load: " + m_Ctx.m_sWorld);
			return;
		}
		foreach (string j : jobs)
		{
			RMT_Context.Say("begin|" + j);
			int code = RunJob(j);
			RMT_Context.Say(string.Format("end|%1|%2", j, code));
			if (code != 0)
			{
				Finish(code, j);
				return;
			}
		}
		Finish(0, m_Ctx.m_sJob);
	}

	//------------------------------------------------------------------------------------------------
	protected int RunJob(string job)
	{
		ref RMT_ChunkJob chunkJob;
		if (job == "terrain")
			chunkJob = new RMT_TerrainJob(m_Ctx, "terrain", "terrain", "t");
		else if (job == "entities")
			chunkJob = new RMT_EntitiesJob(m_Ctx, "entities", "objects", "o");
		else if (job == "surface")
			chunkJob = new RMT_SurfaceJob(m_Ctx, "surface", "surface", "s");
		if (chunkJob)
			return chunkJob.Run();
		if (job == "probe")
			return JobProbe();
		if (job == "mapdata")
			return JobMapData();
		if (job == "roads")
		{
			ref RMT_RoadsJob roads = new RMT_RoadsJob(m_Ctx);
			return roads.Run();
		}
		if (job == "names")
		{
			ref RMT_NamesJob names = new RMT_NamesJob(m_Ctx);
			return names.Run();
		}
		if (job == "ballistics")
		{
			ref RMT_BallisticsJob bal = new RMT_BallisticsJob(m_Ctx);
			return bal.Run();
		}
		if (job == "foliagetrace")
		{
			ref RMT_FoliageTraceJob ft = new RMT_FoliageTraceJob(m_Ctx);
			return ft.Run();
		}
		return 2;
	}

	//------------------------------------------------------------------------------------------------
	// mapdata/: BI's own 2D-map export, the same calls as BI's WorldDataExport command-line plugin
	// (scripts/WorkbenchGame/WorldEditor/SCR_WorldDataExportTool.c): roads, power lines, buildings, areas, water
	// bodies and hills (Geometry2D), plus the shaded land/ocean raster, into a FOLDER given as an OS path.
	protected int JobMapData()
	{
		Workbench.OpenModule(WorldEditor);
		Sleep(300);
		string loaded;
		m_Ctx.m_Api.GetWorldPath(loaded);
		string rel = m_Ctx.m_sOut + "/mapdata";
		RMT_Context.MakeDirs(rel);
		string dir;
		Workbench.GetAbsolutePath(rel, dir, false);
		MapDataExporter exporter = new MapDataExporter();

		DataExportErrorType geo = exporter.ExportData(EMapDataType.Geometry2D, dir, loaded, 50, true);
		RMT_Context.Say(string.Format("mapdata|geometry|%1|%2", typename.EnumToString(DataExportErrorType, geo), dir));

		DataExportErrorType ras = exporter.SetupColors(new Color(1.0, 1.0, 1.0, 1.0), new Color(0.5, 0.5, 0.5, 1.0),
			new Color(0.863, 0.980, 1.0, 1.0), new Color(0.757, 0.91, 0.929, 1.0),
			new Color(0.608, 0.784, 0.529, 1.0), new Color(0.745, 0.745, 0.745, 1.0));
		if (ras == DataExportErrorType.DataExportErrorNone)
			ras = exporter.ExportRasterization(dir, loaded, 2.5, 1.2, 500.0, 60.0, -50.0, 0.5, 1.8, true, 1.25, 1.0);
		RMT_Context.Say(string.Format("mapdata|raster|%1", typename.EnumToString(DataExportErrorType, ras)));

		int items = 0;
		if (geo == DataExportErrorType.DataExportErrorNone)
			items++;
		if (ras == DataExportErrorType.DataExportErrorNone)
			items++;
		string result = "done";
		if (items == 0)
			result = "failed";
		m_Ctx.WriteStatus("mapdata", result, items, 0, 0, items, 0);
		if (items == 0)
			return 1;
		return 0;
	}

	//------------------------------------------------------------------------------------------------
	protected void OnWorldFound(ResourceName resName, string filePath = "")
	{
		m_aWorlds.Insert(resName);
	}

	//------------------------------------------------------------------------------------------------
	// worlds.txt: every .ent world Workbench can see (the game and every loaded addon).
	protected int JobWorlds()
	{
		m_aWorlds.Clear();
		Workbench.SearchResources(OnWorldFound, {"ent"});
		FileHandle f = FileIO.OpenFile(m_Ctx.m_sOut + "/worlds.txt", FileMode.WRITE);
		if (!f)
			return 1;
		foreach (string w : m_aWorlds)
			f.WriteLine(w);
		f.Close();
		m_Ctx.WriteStatus("worlds", "done", 1, 0, 0, m_aWorlds.Count(), 0);
		return 0;
	}

	//------------------------------------------------------------------------------------------------
	// probe.json: what rmt.py needs before the real jobs (bounds, chunk grid, entity count).
	protected int JobProbe()
	{
		string loaded;
		m_Ctx.m_Api.GetWorldPath(loaded);
		vector bmin = m_Ctx.m_vMin;
		vector bmax = m_Ctx.m_vMax;
		FileHandle f = FileIO.OpenFile(m_Ctx.m_sOut + "/probe.json", FileMode.WRITE);
		if (!f)
			return 1;
		f.WriteLine("{");
		f.WriteLine(string.Format("  \"world\": \"%1\",", loaded));
		f.WriteLine(string.Format("  \"min\": [%1, %2, %3],", bmin[0], bmin[1], bmin[2]));
		f.WriteLine(string.Format("  \"max\": [%1, %2, %3],", bmax[0], bmax[1], bmax[2]));
		f.WriteLine(string.Format("  \"tile\": %1,", m_Ctx.m_fTile));
		f.WriteLine(string.Format("  \"cols\": %1,", m_Ctx.m_iCols));
		f.WriteLine(string.Format("  \"rows\": %1,", m_Ctx.m_iRows));
		f.WriteLine(string.Format("  \"editorEntities\": %1", m_Ctx.m_Api.GetEditorEntityCount()));
		f.WriteLine("}");
		f.Close();
		m_Ctx.WriteStatus("probe", "done", 1, 0, 0, m_Ctx.m_Api.GetEditorEntityCount(), 0);
		return 0;
	}
}
