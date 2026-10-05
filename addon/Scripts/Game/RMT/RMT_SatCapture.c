// Satellite capture, game side (Game script module: world entities must live here).
// Modelled on BI's Screenshot_Autotest (scripts/GameLib/entities/autotest/Screenshot_Autotest.c): an entity with a
// frame event moves a camera to each spot, preloads it, waits, takes a BMP screenshot over a few frames, and at the
// end asks the game to close. It never blocks the engine, so every frame is really drawn.
//
// It runs only in the real game: rmt.py starts it with -rmtSat 1 and RMT_GameHook spawns this entity once the world
// is loaded (command-line Workbench does not draw, so its screenshots are black). The settings come from the command
// line:
//   -rmtOut=$profile:...        run folder; pictures go to <out>/satellite/<name>.bmp (+ .txt, written only once the
//                               picture is on disk and not empty; it is also the resume marker)
//   -rmtSatCenters=x,z;x,z      spots (tests), or -rmtSatGrid=x0,z0,cols,rows,step for a whole grid
//   -rmtSatSpan=<m>             ground metres across the picture's height
//   -rmtSatFov=<deg>            the lens (perspective, the default and the only mode that works)
//   -rmtSatMode=0               orthographic: BROKEN, renders black in this engine build; kept only for testing it
//   -rmtSatHeight=<m>           camera height
//   -rmtSatWait=<s>             settle time after preload, default 1.5
// Noon and a clear sky are asked for first, and no picture is taken until the weather manager reports both.
// When done it writes <out>/satellite.status.json (RMT_Status) and asks the game to close.

class RMT_SatCaptureEntityClass : GenericEntityClass
{
}

class RMT_SatCaptureEntity : GenericEntity
{
	protected string m_sOut;
	protected ref array<float> m_aX = {};
	protected ref array<float> m_aZ = {};
	protected ref array<string> m_aName = {};
	protected float m_fSpan = 256;
	protected float m_fHeight = 1000;
	protected float m_fWait = 1.5;

	protected CameraBase m_Camera;
	protected int m_iShot = -1;
	protected int m_iPhase;      // 0 preloading, 1 settling, 2 saving
	protected float m_fTimer;
	protected bool m_bReady;
	protected bool m_bDone;
	protected int m_iSkipped;
	protected int m_iMode;       // 1 perspective (default); 0 orthographic renders black in this engine build
	protected float m_fFov;      // vertical field of view, degrees
	protected int m_iBaseline;   // test: 0 not yet, 1 shot requested, 2 done
	protected int m_iFailed;     // pictures that never reached the disk
	protected int m_iMade;
	protected string m_sFailReason;
	protected bool m_bWeatherOk; // noon and clear sky have taken effect
	protected BaseWeatherManagerEntity m_Weather;
	protected vector m_vCamPos;  // where the camera was put for the current shot

	//------------------------------------------------------------------------------------------------
	protected static void Say(string msg)
	{
		Print("RMT|" + msg, LogLevel.NORMAL);
	}

	//------------------------------------------------------------------------------------------------
	protected static string Param(string name, string fallback = "")
	{
		string v;
		if (System.GetCLIParam(name, v) && v != "")
			return v;
		return fallback;
	}

	//------------------------------------------------------------------------------------------------
	void RMT_SatCaptureEntity(IEntitySource src, IEntity parent)
	{
		SetEventMask(EntityEvent.INIT | EntityEvent.FRAME);
		SetFlags(EntityFlags.ACTIVE, true);
	}

	//------------------------------------------------------------------------------------------------
	protected void ReadPlan()
	{
		m_sOut = Param("rmtOut") + "/satellite";
		m_fSpan = Param("rmtSatSpan", "256").ToFloat();
		m_fHeight = Param("rmtSatHeight", "1000").ToFloat();
		m_fWait = Param("rmtSatWait", "1.5").ToFloat();
		m_iMode = Param("rmtSatMode", "1").ToInt();
		m_fFov = Param("rmtSatFov", "15").ToFloat();
		string grid = Param("rmtSatGrid");
		if (grid != "")
		{
			array<string> g = {};
			grid.Split(",", g, true);
			if (g.Count() < 5)
			{
				m_sFailReason = "-rmtSatGrid needs x0,z0,cols,rows,step: " + grid;
				return;
			}
			float x0 = g[0].ToFloat();
			float z0 = g[1].ToFloat();
			int cols = g[2].ToInt();
			int rows = g[3].ToInt();
			float step = g[4].ToFloat();
			for (int r = 0; r < rows; r++)
			{
				for (int c = 0; c < cols; c++)
				{
					string name = string.Format("s_%1_%2", c, r);
					if (FileIO.FileExists(m_sOut + "/" + name + ".txt"))
					{
						m_iSkipped++;
						continue; // done in an earlier run
					}
					m_aX.Insert(x0 + (c + 0.5) * step);
					m_aZ.Insert(z0 + (r + 0.5) * step);
					m_aName.Insert(name);
				}
			}
			return;
		}
		array<string> spots = {};
		Param("rmtSatCenters").Split(";", spots, true);
		foreach (int i, string spot : spots)
		{
			array<string> xz = {};
			spot.Split(",", xz, true);
			if (xz.Count() != 2)
				continue;
			m_aX.Insert(xz[0].ToFloat());
			m_aZ.Insert(xz[1].ToFloat());
			m_aName.Insert(string.Format("test_%1", i));
		}
	}

	//------------------------------------------------------------------------------------------------
	// Noon, clear sky, as BI's autotest does it.
	protected void SetNoon()
	{
		BaseWeatherManagerEntity weather = BaseWeatherManagerEntity.Cast(WeatherManager.GetRegisteredWeatherManagerEntity(GetWorld()));
		m_Weather = weather;
		if (!weather)
		{
			Say("sat|no weather manager (lighting as the world has it)");
			m_bWeatherOk = true;
			return;
		}
		weather.SetDate(1989, 6, 21, true);
		weather.SetTimeOfTheDay(12.0, true);
		BaseWeatherStateTransitionManager trans = weather.GetTransitionManager();
		if (trans)
		{
			WeatherStateTransitionNode node = trans.CreateStateTransition("Clear", 0.1, 0.1);
			if (node)
			{
				trans.EnqueueStateTransition(node, false);
				trans.RequestStateTransitionImmediately(node);
			}
		}
	}

	//------------------------------------------------------------------------------------------------
	// True once the asked-for noon and clear sky are what the weather manager reports.
	protected bool WeatherReady()
	{
		if (m_bWeatherOk || !m_Weather)
			return true;
		bool noon = Math.AbsFloat(m_Weather.GetTimeOfTheDay() - 12.0) < 0.1;
		bool clear = true;
		BaseWeatherStateTransitionManager trans = m_Weather.GetTransitionManager();
		if (trans && trans.GetCurrentState())
			clear = trans.GetCurrentState().GetStateName() == "Clear";
		m_bWeatherOk = noon && clear;
		return m_bWeatherOk;
	}

	//------------------------------------------------------------------------------------------------
	protected bool Setup()
	{
		ReadPlan();
		FileIO.MakeDirectory(m_sOut);
		if (m_sFailReason != "")
			return false;
		if (m_aX.IsEmpty() && m_iSkipped == 0)
		{
			m_sFailReason = "nothing to photograph (no -rmtSatGrid or -rmtSatCenters)";
			return false;
		}
		m_Camera = CameraBase.Cast(GetWorld().FindEntityByName("RMT_Camera"));
		if (!m_Camera)
		{
			EntitySpawnParams params = new EntitySpawnParams();
			params.TransformMode = ETransformMode.WORLD;
			m_Camera = CameraBase.Cast(GetGame().SpawnEntity(CameraBase, GetWorld(), params));
		}
		CameraManager cm = GetGame().GetCameraManager();
		if (m_Camera && cm)
			cm.SetCamera(m_Camera);
		Say(string.Format("sat|setup|shots=%1|skipped=%2|camera=%3|manager=%4|span=%5", m_aX.Count(), m_iSkipped, m_Camera != null, cm != null, m_fSpan));
		if (m_iMode == 0)
			Say("warn|sat|orthographic mode is broken in this engine build (black pictures)");
		SetNoon();
		return true;
	}

	//------------------------------------------------------------------------------------------------
	protected int CameraIndex()
	{
		if (m_Camera)
			return m_Camera.GetCameraIndex();
		return GetWorld().GetCurrentCameraId();
	}

	//------------------------------------------------------------------------------------------------
	protected void PlaceCamera()
	{
		vector pos = Vector(m_aX[m_iShot], m_fHeight, m_aZ[m_iShot]);
		vector mat[4];
		Math3D.AnglesToMatrix(Vector(0, -90, 0), mat); // yaw 0 (north up), pitch straight down
		mat[3] = pos;
		m_vCamPos = pos;
		BaseWorld world = GetWorld();
		int cam = CameraIndex();
		if (m_Camera)
		{
			m_Camera.SetTransform(mat);
			if (m_iMode == 0)
				m_Camera.SetVerticalFOV(m_fSpan);
			m_Camera.SetNearPlane(1);
			m_Camera.SetFarPlane(m_fHeight + 2000);
		}
		else
			world.SetCameraEx(cam, mat);
		if (m_iMode == 1)
		{
			// a narrow lens from high up; rmt.py corrects each shot to a map using the exported terrain
			if (m_Camera)
				m_Camera.SetFOVDegree(m_fFov);
			world.SetCameraType(cam, CameraType.PERSPECTIVE);
		}
		else
		{
			world.SetCameraType(cam, CameraType.ORTHOGRAPHIC);
			world.SetCameraVerticalFOV(cam, m_fSpan);
		}
		world.SetCameraNearPlane(cam, 1);
		world.SetCameraFarPlane(cam, m_fHeight + 2000);
	}

	//------------------------------------------------------------------------------------------------
	protected void Next()
	{
		m_iShot++;
		m_iPhase = 0;
		m_fTimer = 0;
		if (m_iShot >= m_aX.Count())
		{
			Finish();
			return;
		}
		PlaceCamera();
		GetGame().BeginPreload(GetWorld(), Vector(m_aX[m_iShot], 0, m_aZ[m_iShot]), m_fSpan * 1.5);
	}

	//------------------------------------------------------------------------------------------------
	protected void Finish()
	{
		m_bDone = true;
		Say(string.Format("sat|done|shots=%1|made=%2|failed=%3", m_aX.Count(), m_iMade, m_iFailed));
		string result = "done";
		string reason = m_sFailReason;
		if (reason != "" || m_iMade + m_iSkipped == 0)
		{
			result = "failed";
			if (reason == "")
				reason = "no picture reached the disk";
		}
		else if (m_iFailed > 0)
		{
			result = "partial";
			reason = string.Format("%1 picture(s) never reached the disk; run again to retake them", m_iFailed);
		}
		RMT_Status.Write("satellite", result, m_iMade, m_iSkipped, m_iFailed, m_iMade + m_iSkipped, reason);
		GetGame().RequestClose();
	}

	//------------------------------------------------------------------------------------------------
	protected bool PictureOnDisk(string stem)
	{
		return RMT_Status.FileSize(stem + ".bmp") > 0 || RMT_Status.FileSize(stem + ".png") > 0;
	}

	//------------------------------------------------------------------------------------------------
	override void EOnFrame(IEntity owner, float timeSlice)
	{
		if (m_bDone)
			return;
		// test: one picture of whatever the game shows before the camera is touched
		if (m_iBaseline < 2 && Param("rmtSatBaseline") != "")
		{
			m_fTimer += timeSlice;
			if (m_iBaseline == 0 && m_fTimer > 8)
			{
				FileIO.MakeDirectory(Param("rmtOut") + "/satellite");
				System.MakeScreenshot(Param("rmtOut") + "/satellite/baseline");
				m_iBaseline = 1;
				m_fTimer = 0;
			}
			else if (m_iBaseline == 1 && m_fTimer > 1)
			{
				Say(string.Format("sat|baseline|camera=%1", GetWorld().GetCurrentCameraId()));
				m_iBaseline = 2;
				m_fTimer = 0;
			}
			return;
		}
		if (!m_bReady)
		{
			m_bReady = true;
			if (!Setup())
			{
				Finish();
				return;
			}
			Next();
			return;
		}
		// the camera is placed once per shot (moving it every frame keeps the streamer from settling); put back only
		// if something else moved it
		if (m_Camera && vector.Distance(m_Camera.GetOrigin(), m_vCamPos) > 0.01)
			PlaceCamera();
		m_fTimer += timeSlice;
		if (m_iPhase == 0)
		{
			if (!GetGame().IsPreloadFinished() && m_fTimer < 30)
				return;
			if (!WeatherReady())
			{
				if (m_fTimer < 120)
					return;
				Say("warn|sat|noon and clear sky not reported after 120 s; shooting anyway");
				m_bWeatherOk = true;
			}
			m_iPhase = 1;
			m_fTimer = 0;
			return;
		}
		if (m_iPhase == 1)
		{
			if (m_fTimer < m_fWait)
				return;
			System.MakeScreenshot(m_sOut + "/" + m_aName[m_iShot]);
			m_iPhase = 2;
			m_fTimer = 0;
			return;
		}
		// the screenshot is written over several frames; the .txt (also the resume marker) only once it is on disk
		string stem = m_sOut + "/" + m_aName[m_iShot];
		if (!PictureOnDisk(stem))
		{
			if (m_fTimer < 30)
				return;
			Say(string.Format("error|sat|picture not written|%1", m_aName[m_iShot]));
			m_iFailed++;
			Next();
			return;
		}
		FileHandle f = FileIO.OpenFile(stem + ".txt", FileMode.WRITE);
		if (f)
		{
			f.WriteLine("x,z,span,height,fov,mode");
			f.WriteLine(string.Format("%1,%2,%3,%4,%5,%6", m_aX[m_iShot], m_aZ[m_iShot], m_fSpan, m_fHeight, m_fFov, m_iMode));
			f.Close();
		}
		m_iMade++;
		Say(string.Format("sat|shot|%1|left=%2", m_aName[m_iShot], m_aX.Count() - m_iShot - 1));
		Next();
	}
}
