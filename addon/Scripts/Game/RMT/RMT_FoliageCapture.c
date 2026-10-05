// Foliage photographs, game side: how see-through each kind of tree and bush is, measured from what the game draws,
// at every distance that matters for line of sight.
//
// Physics rays go through leaves (checked: every ray setting, including TraceFlags.VISIBILITY and the Foliage /
// ViewGeometry / Vegetation layers, only hits trunks and branches), so plants are photographed instead: the method of
// the old EveronFoliageMeasureTool, automated and run in the game (command-line Workbench does not draw). Distance
// matters: the game swaps in simpler, denser models further away (a tall spruce reads 0.56 close up, 0.79 at 150 m).
//
// rmt.py starts the game on an empty world with -rmtFoliage 1 -rmtOut=$profile:<run>; RMT_GameHook spawns this entity.
// It reads <run>/foliage/plants.csv (prefab,kind,count,mean_scale). For each plant it spawns one FoliageLift m above
// the ground, and takes these views, each as two screenshots, <id>_a (plant shown) and <id>_b (plant hidden):
//   <key>_0_<s>          FoliageSides sides close up (backed off until the plant fits the frame)
//   <key>_top            straight up from below, the crown against the sky
//   <key>_d<m>_<s>       FoliageSides sides again from each of the FoliageLod distances (metres), same lens
// The plant is turned for each side; the camera always looks north from the south, at a standing player's eye height
// (EYE_HEIGHT above the plant's base), so what is behind the plant is sky or distant land. The plant is told apart from
// it by the shown/hidden pair, not by the sky.
// Every shot waits until the camera and the distance have been still for FoliageSettleFrames frames (default 30) and
// at least FoliageSettle seconds (default 0.5), so the game has swapped to the model it draws at that distance; the
// hidden shot waits the same after the plant is hidden. A top view whose camera would have to sit lower than the lift
// allows (the crown is too wide) is skipped and said so (<id>_skip.txt), never stored clipped.
// Rows go to <run>/foliage/shots.csv (the old tool's columns plus `view`), so the same analysis applies. A plant is
// finished only when both pictures of every view are on disk and not empty and its rows are in shots.csv; finished
// plants are skipped, so a stopped run carries on. At the end: <run>/foliage.status.json (RMT_Status), then close.

class RMT_FoliageCaptureEntityClass : GenericEntityClass
{
}

class RMT_FoliageCaptureEntity : GenericEntity
{
	static const float EYE_HEIGHT = 1.7;

	protected string m_sOut;
	protected ref array<string> m_aPrefab = {};
	protected ref array<string> m_aKind = {};
	protected int m_iSides = 8;
	protected float m_fFov = 40;
	protected float m_fLift = 60;
	protected bool m_bTop = true;
	protected ref array<float> m_aLod = {};
	protected vector m_vSpot;

	// the current plant's views, in order
	protected ref array<string> m_aViewId = {};
	protected ref array<string> m_aViewKind = {};   // side, top, far
	protected ref array<float> m_aViewYaw = {};
	protected ref array<float> m_aViewDist = {};    // 0 = back off until it fits

	protected CameraBase m_Camera;
	protected IEntity m_Plant;
	protected string m_sKey;
	protected float m_fBaseY;
	protected int m_iPlant = -1;
	protected int m_iView;
	protected int m_iStep;
	protected float m_fTimer;
	protected bool m_bReady;
	protected bool m_bDone;
	protected int m_iShots;
	protected int m_iSkipped;       // finished in an earlier run
	protected int m_iFailed;        // could not be spawned or framed
	protected int m_iViewsSkipped;  // top views that did not fit under the lift
	protected int m_iFrames;        // frames since the camera, the distance or the plant's visibility last changed
	protected int m_iSettleFrames = 30;
	protected float m_fSettle = 0.5;
	protected string m_sFailReason;
	protected string m_sWind;       // -rmtFoliageWind=<m/s>: hold the wind at this speed (0 = the plants at rest)
	// research: -rmtFoliageOverlay=<profile-relative csv> "key,x0,y0,z0,x1,y1,z1,x2,y2,z2" triangles in the plant's own
	// coordinates (a mesh decoded outside the game). For each side view of a listed plant one more picture, <id>_t, is
	// taken with the plant hidden and those triangles drawn as flat debug shapes, to check the decoded mesh against
	// what the game draws from the same camera.
	protected ref map<string, ref array<vector>> m_mOverlay = new map<string, ref array<vector>>();
	protected ref array<ref Shape> m_aShapes = {};
	protected ref set<string> m_aRowsDone = new set<string>();  // view ids already in shots.csv
	protected ref FileHandle m_Csv;
	protected vector m_vCam;
	protected float m_fPitch;
	protected float m_fDist;
	protected vector m_vMin;
	protected vector m_vMax;

	//------------------------------------------------------------------------------------------------
	protected static void Say(string msg)
	{
		Print("RMT|" + msg, LogLevel.NORMAL);
	}

	protected static string Param(string name, string fallback = "")
	{
		string v;
		if (System.GetCLIParam(name, v) && v != "")
			return v;
		return fallback;
	}

	//------------------------------------------------------------------------------------------------
	void RMT_FoliageCaptureEntity(IEntitySource src, IEntity parent)
	{
		SetEventMask(EntityEvent.FRAME);
		SetFlags(EntityFlags.ACTIVE, true);
	}

	//------------------------------------------------------------------------------------------------
	protected bool Setup()
	{
		m_sOut = Param("rmtOut") + "/foliage";
		FileIO.MakeDirectory(m_sOut);
		m_iSettleFrames = Param("rmtFoliageSettleFrames", "30").ToInt();
		m_sWind = Param("rmtFoliageWind");
		string overlay = Param("rmtFoliageOverlay");
		if (overlay != "")
		{
			FileHandle ov = FileIO.OpenFile("$profile:" + overlay, FileMode.READ);
			if (ov)
			{
				string ol;
				while (ov.ReadLine(ol) >= 0)
				{
					array<string> c = {};
					ol.Split(",", c, false);
					if (c.Count() != 10)
						continue;
					array<vector> tris = m_mOverlay.Get(c[0]);
					if (!tris)
					{
						tris = {};
						m_mOverlay.Set(c[0], tris);
					}
					for (int k = 0; k < 3; k++)
						tris.Insert(Vector(c[1 + k * 3].ToFloat(), c[2 + k * 3].ToFloat(), c[3 + k * 3].ToFloat()));
				}
				ov.Close();
				Say(string.Format("foliage|overlay|plants=%1", m_mOverlay.Count()));
			}
		}
		m_fSettle = Param("rmtFoliageSettle", "0.5").ToFloat();
		m_iSides = Param("rmtFoliageSides", "8").ToInt();
		m_fFov = Param("rmtFoliageFov", "40").ToFloat();
		m_fLift = Param("rmtFoliageLift", "60").ToFloat();
		m_bTop = Param("rmtFoliageTop", "1").ToInt() != 0;
		array<string> lods = {};
		Param("rmtFoliageLod").Split(",", lods, true);
		foreach (string d : lods)
			m_aLod.Insert(d.ToFloat());
		FileHandle f = FileIO.OpenFile(m_sOut + "/plants.csv", FileMode.READ);
		if (!f)
		{
			m_sFailReason = "no plants.csv in " + m_sOut;
			return false;
		}
		string row;
		bool header = true;
		while (f.ReadLine(row) >= 0)
		{
			if (header)
			{
				header = false;
				continue;
			}
			array<string> cols = {};
			row.Split(",", cols, false);
			if (cols.Count() < 2)
				continue;
			m_aPrefab.Insert(cols[0]);
			m_aKind.Insert(cols[1]);
		}
		f.Close();
		if (m_aPrefab.IsEmpty())
		{
			m_sFailReason = "plants.csv lists no plants";
			return false;
		}

		// the spot (rmt.py passes the empty world's middle), lifted well clear of the ground and the sea
		array<string> xz = {};
		Param("rmtFoliageSpot", "2048,2048").Split(",", xz, true);
		if (xz.Count() != 2)
		{
			m_sFailReason = "-rmtFoliageSpot needs x,z";
			return false;
		}
		float x = xz[0].ToFloat();
		float z = xz[1].ToFloat();
		float ground = Math.Max(GetWorld().GetSurfaceY(x, z), 0);
		m_vSpot = Vector(x, ground + m_fLift, z);

		EntitySpawnParams params = new EntitySpawnParams();
		params.TransformMode = ETransformMode.WORLD;
		m_Camera = CameraBase.Cast(GetGame().SpawnEntity(CameraBase, GetWorld(), params));
		CameraManager cm = GetGame().GetCameraManager();
		if (m_Camera && cm)
			cm.SetCamera(m_Camera);
		SetNoon();

		if (!m_Camera)
		{
			m_sFailReason = "no camera";
			return false;
		}
		string csvPath = m_sOut + "/shots.csv";
		bool isNew = RMT_Status.FileSize(csvPath) <= 0;
		if (!isNew)
		{
			// the views whose rows are already written (a picture without its row is shot again)
			FileHandle old = FileIO.OpenFile(csvPath, FileMode.READ);
			if (old)
			{
				string done;
				while (old.ReadLine(done) >= 0)
				{
					int comma = done.IndexOf(",");
					if (comma > 0)
						m_aRowsDone.Insert(done.Substring(0, comma));
				}
				old.Close();
			}
		}
		m_Csv = FileIO.OpenFile(csvPath, FileMode.APPEND);
		if (!m_Csv)
		{
			m_sFailReason = "could not open " + csvPath;
			return false;
		}
		if (isNew)
			m_Csv.WriteLine("id,prefab,kind,x,z,ground,height,minx,miny,minz,maxx,maxy,maxz,camx,camy,camz,dirx,dirz,yaw,pitch,fov,dist,view");
		Say(string.Format("foliage|setup|plants=%1|sides=%2|distances=%3|spot=%4|camera=%5", m_aPrefab.Count(), m_iSides, m_aLod.Count(), m_vSpot, m_Camera != null));
		return true;
	}

	//------------------------------------------------------------------------------------------------
	protected void SetNoon()
	{
		BaseWeatherManagerEntity weather = BaseWeatherManagerEntity.Cast(WeatherManager.GetRegisteredWeatherManagerEntity(GetWorld()));
		if (!weather)
			return;
		weather.SetDate(1989, 6, 21, true);
		weather.SetTimeOfTheDay(12.0, true);
		if (m_sWind != "")
		{
			weather.SetWindSpeedOverride(true, m_sWind.ToFloat());
			weather.SetWindDirectionOverride(true, 0);
		}
		BaseWeatherStateTransitionManager trans = weather.GetTransitionManager();
		if (!trans)
			return;
		WeatherStateTransitionNode node = trans.CreateStateTransition("Clear", 0.1, 0.1);
		if (node)
		{
			trans.EnqueueStateTransition(node, false);
			trans.RequestStateTransitionImmediately(node);
		}
	}

	//------------------------------------------------------------------------------------------------
	// A short, file-name-safe name for a prefab: its file name plus its resource id (as the old tool).
	protected string KeyOf(string prefab)
	{
		string guid = "";
		int close = prefab.IndexOf("}");
		if (prefab.IndexOf("{") == 0 && close > 1)
			guid = prefab.Substring(1, close - 1);
		string file = prefab;
		int slash = prefab.LastIndexOf("/");
		if (slash >= 0)
			file = prefab.Substring(slash + 1, prefab.Length() - slash - 1);
		int dot = file.LastIndexOf(".");
		if (dot > 0)
			file = file.Substring(0, dot);
		if (guid != "")
			return file + "_" + guid;
		return file;
	}

	//------------------------------------------------------------------------------------------------
	// Every view of one plant, in shooting order.
	protected void PlanViews(string key)
	{
		m_aViewId.Clear();
		m_aViewKind.Clear();
		m_aViewYaw.Clear();
		m_aViewDist.Clear();
		for (int s = 0; s < m_iSides; s++)
			AddView(key + "_0_" + s, "side", s * 360.0 / m_iSides, 0);
		if (m_bTop)
			AddView(key + "_top", "top", 0, 0);
		foreach (float d : m_aLod)
		{
			for (int s2 = 0; s2 < m_iSides; s2++)
				AddView(string.Format("%1_d%2_%3", key, Math.Round(d), s2), "far", s2 * 360.0 / m_iSides, d);
		}
	}

	protected void AddView(string id, string kind, float yaw, float dist)
	{
		m_aViewId.Insert(id);
		m_aViewKind.Insert(kind);
		m_aViewYaw.Insert(yaw);
		m_aViewDist.Insert(dist);
	}

	//------------------------------------------------------------------------------------------------
	protected void SetCamera(vector pos, float pitchDeg)
	{
		vector mat[4];
		Math3D.AnglesToMatrix(Vector(0, pitchDeg, 0), mat); // looking north, pitched
		mat[3] = pos;
		if (m_Camera)
		{
			m_Camera.SetTransform(mat);
			m_Camera.SetFOVDegree(m_fFov);
			m_Camera.SetNearPlane(0.1);
			m_Camera.SetFarPlane(3000);
		}
		else
			GetWorld().SetCameraEx(GetWorld().GetCurrentCameraId(), mat);
	}

	//------------------------------------------------------------------------------------------------
	// Camera height for a side view: a standing player's eye, EYE_HEIGHT above the plant's base, as in play. What is
	// behind the plant is sky or distant land; the plant is told apart by the shown/hidden pair, not by the sky.
	protected float SideCamY(float dist)
	{
		return m_fBaseY + EYE_HEIGHT;
	}

	//------------------------------------------------------------------------------------------------
	// Places the camera for the current view: south of the plant looking north (pitched to centre it), or straight
	// up from below for the top view.
	protected bool PlaceCamera()
	{
		m_Plant.GetWorldBounds(m_vMin, m_vMax);
		float cx = (m_vMin[0] + m_vMax[0]) * 0.5;
		float cz = (m_vMin[2] + m_vMax[2]) * 0.5;
		float h = m_vMax[1] - m_fBaseY;
		float halfW = Math.Max(m_vMax[0] - m_vMin[0], m_vMax[2] - m_vMin[2]) * 0.5;
		float vHalf = m_fFov * 0.5 * Math.DEG2RAD;
		string kind = m_aViewKind[m_iView];
		if (kind == "top")
		{
			m_fDist = Math.Max(3, halfW / Math.Tan(vHalf) * 1.25 + 1);
			if (m_fDist > m_fLift - 2)
				return false; // the crown would be clipped: the view is skipped rather than stored cut off
			m_fPitch = 90;
			m_vCam = Vector(cx, m_fBaseY - m_fDist, cz);
			SetCamera(m_vCam, m_fPitch);
			return true;
		}
		if (kind == "far")
		{
			m_fDist = m_aViewDist[m_iView];
			float camYf = SideCamY(m_fDist);
			m_fPitch = Math.Atan2(m_fBaseY + h * 0.5 - camYf, m_fDist) * Math.RAD2DEG;
			m_vCam = Vector(cx, camYf, cz - m_fDist);
			SetCamera(m_vCam, m_fPitch);
			return true;
		}
		// close up: back off until the plant fits (frame assumed at least 4:3)
		float hHalf = Math.Atan2(Math.Tan(vHalf) * 1.33, 1);
		float dist = Math.Max(3, halfW + 1);
		float camY = SideCamY(dist);
		float pitch = 0;
		bool fits = false;
		for (int tries = 0; tries < 40 && !fits; tries++)
		{
			camY = SideCamY(dist);
			float aTop = Math.Atan2(m_fBaseY + h - camY, dist);
			float aBase = Math.Atan2(m_fBaseY - camY, dist);
			float aSide = Math.Atan2(halfW, dist - halfW);
			pitch = (aTop + aBase) * 0.5;
			if (aTop - aBase < vHalf * 2 * 0.85 && aSide < hHalf * 0.85)
				fits = true;
			else
				dist = dist * 1.12;
		}
		if (!fits)
			return false;
		m_fDist = dist;
		m_fPitch = pitch * Math.RAD2DEG;
		m_vCam = Vector(cx, camY, cz - dist);
		SetCamera(m_vCam, m_fPitch);
		return true;
	}

	//------------------------------------------------------------------------------------------------
	protected void NextView()
	{
		m_iView++;
		m_iStep = 0;
		m_fTimer = 0;
		m_iFrames = 0;
		if (m_iView >= m_aViewId.Count())
		{
			Say(string.Format("foliage|plant|%1|%2|left=%3", m_iPlant, m_sKey, m_aPrefab.Count() - m_iPlant - 1));
			NextPlant();
		}
	}

	//------------------------------------------------------------------------------------------------
	protected void WriteRow()
	{
		float cx = (m_vMin[0] + m_vMax[0]) * 0.5;
		float cz = (m_vMin[2] + m_vMax[2]) * 0.5;
		string line = string.Format("%1,%2,%3,%4,%5,%6,%7,", m_aViewId[m_iView], m_aPrefab[m_iPlant], m_aKind[m_iPlant], cx, cz, m_fBaseY, m_vMax[1] - m_fBaseY);
		line += string.Format("%1,%2,%3,%4,%5,%6,", m_vMin[0], m_vMin[1], m_vMin[2], m_vMax[0], m_vMax[1], m_vMax[2]);
		line += string.Format("%1,%2,%3,%4,%5,", m_vCam[0], m_vCam[1], m_vCam[2], 0, 1);
		line += string.Format("%1,%2,%3,%4,%5", m_aViewYaw[m_iView], m_fPitch, m_fFov, m_fDist, m_aViewKind[m_iView]);
		m_Csv.WriteLine(line);
	}

	//------------------------------------------------------------------------------------------------
	protected void RemovePlant()
	{
		if (m_Plant)
			SCR_EntityHelper.DeleteEntityAndChildren(m_Plant);
		m_Plant = null;
	}

	//------------------------------------------------------------------------------------------------
	protected void NextPlant()
	{
		RemovePlant();
		m_iPlant++;
		while (m_iPlant < m_aPrefab.Count())
		{
			m_sKey = KeyOf(m_aPrefab[m_iPlant]);
			PlanViews(m_sKey);
			if (!Finished())
				break;
			m_iSkipped++;
			m_iPlant++;
		}
		if (m_iPlant >= m_aPrefab.Count())
		{
			Finish();
			return;
		}
		Resource res = Resource.Load(m_aPrefab[m_iPlant]);
		EntitySpawnParams params = new EntitySpawnParams();
		params.TransformMode = ETransformMode.WORLD;
		params.Transform[3] = m_vSpot;
		if (res && res.IsValid())
			m_Plant = GetGame().SpawnEntityPrefab(res, GetWorld(), params);
		if (!m_Plant)
		{
			Say("error|foliage|could not spawn " + m_aPrefab[m_iPlant]);
			m_iFailed++;
			NextPlant();
			return;
		}
		m_fBaseY = m_Plant.GetOrigin()[1];
		m_iView = 0;
		m_iStep = 0;
		m_fTimer = 0;
		m_iFrames = 0;
		GetGame().BeginPreload(GetWorld(), m_vSpot, 200);
	}

	//------------------------------------------------------------------------------------------------
	protected bool Shot(string stem)
	{
		return RMT_Status.FileSize(stem + ".bmp") > 0 || RMT_Status.FileSize(stem + ".png") > 0;
	}

	//------------------------------------------------------------------------------------------------
	// The current plant is finished when every view has both pictures and its row (or was skipped as too wide).
	protected bool Finished()
	{
		foreach (string id : m_aViewId)
		{
			if (FileIO.FileExists(m_sOut + "/" + id + "_skip.txt"))
				continue;
			string stem = m_sOut + "/" + id;
			if (!Shot(stem + "_a") || !Shot(stem + "_b") || !m_aRowsDone.Contains(id))
				return false;
		}
		return true;
	}

	//------------------------------------------------------------------------------------------------
	// Camera, distance and visibility have been still long enough for the drawn model to have caught up.
	protected bool Settled()
	{
		return m_iFrames >= m_iSettleFrames && m_fTimer >= m_fSettle;
	}

	//------------------------------------------------------------------------------------------------
	protected void Finish()
	{
		m_bDone = true;
		RemovePlant();
		if (m_Csv)
			m_Csv.Close();
		int made = m_aPrefab.Count() - m_iSkipped - m_iFailed;
		Say(string.Format("foliage|done|plants=%1|skipped=%2|failed=%3|shots=%4|views_skipped=%5", m_aPrefab.Count(), m_iSkipped, m_iFailed, m_iShots, m_iViewsSkipped));
		string result = "done";
		string reason = m_sFailReason;
		if (reason != "" || made + m_iSkipped <= 0)
		{
			result = "failed";
			if (reason == "")
				reason = "no plant was photographed";
		}
		else if (m_iFailed > 0)
		{
			result = "partial";
			reason = string.Format("%1 plant(s) could not be spawned or framed", m_iFailed);
		}
		string extra = string.Format("\"views_skipped\": %1, ", m_iViewsSkipped);
		RMT_Status.Write("foliage", result, Math.Max(made, 0), m_iSkipped, m_iFailed, m_iShots, reason, extra);
		GetGame().RequestClose();
	}

	//------------------------------------------------------------------------------------------------
	// One view: 0 turn the plant and place the camera; 1 wait for detail, shot "_a"; 2 hide the plant;
	// 3 shot "_b"; 4 show it again, next view.
	override void EOnFrame(IEntity owner, float timeSlice)
	{
		if (m_bDone)
			return;
		if (!m_bReady)
		{
			m_bReady = true;
			if (!Setup())
			{
				Finish();
				return;
			}
			NextPlant();
			return;
		}
		m_fTimer += timeSlice;
		m_iFrames++;
		string path = m_sOut + "/" + m_aViewId[m_iView];
		switch (m_iStep)
		{
			case 0:
			{
				if (m_iView == 0 && m_fTimer < 2)
					return; // the model and its textures load
				m_Plant.SetYawPitchRoll(Vector(m_aViewYaw[m_iView], 0, 0));
				m_Plant.Update();
				if (!PlaceCamera())
				{
					if (m_aViewKind[m_iView] == "top")
					{
						// too wide to frame from below the lift: no top view for this plant, said so
						Say("warn|foliage|top view skipped, crown wider than the lift allows: " + m_sKey);
						FileHandle skip = FileIO.OpenFile(path + "_skip.txt", FileMode.WRITE);
						if (skip)
						{
							skip.WriteLine("crown wider than the lift allows");
							skip.Close();
						}
						m_iViewsSkipped++;
						NextView();
						return;
					}
					Say("error|foliage|does not fit the frame: " + m_sKey);
					m_iFailed++;
					NextPlant();
					return;
				}
				m_iStep = 1;
				m_fTimer = 0;
				m_iFrames = 0;
				return;
			}
			case 1:
			{
				if (!Settled())
					return; // the model the game draws at this distance, and its textures, load
				System.MakeScreenshot(path + "_a");
				m_iStep = 2;
				m_fTimer = 0;
				m_iFrames = 0;
				return;
			}
			case 2:
			{
				if (!Shot(path + "_a"))
				{
					if (m_fTimer > 30)
					{
						m_sFailReason = "a screenshot was not written: " + path + "_a";
						Finish();
					}
					return; // the picture is written over several frames
				}
				m_Plant.ClearFlags(EntityFlags.VISIBLE, true);
				m_iStep = 3;
				m_fTimer = 0;
				m_iFrames = 0;
				return;
			}
			case 3:
			{
				if (!Settled())
					return; // the plant is gone from the drawn frame, not just flagged hidden
				System.MakeScreenshot(path + "_b");
				m_iStep = 4;
				m_fTimer = 0;
				m_iFrames = 0;
				return;
			}
			case 4:
			{
				if (!Shot(path + "_b"))
				{
					if (m_fTimer > 30)
					{
						m_sFailReason = "a screenshot was not written: " + path + "_b";
						Finish();
					}
					return;
				}
				if (m_aViewKind[m_iView] == "side" && m_mOverlay.Contains(m_sKey))
				{
					// the decoded triangles, flat, the plant still hidden
					array<vector> tris = m_mOverlay.Get(m_sKey);
					for (int t = 0; t + 2 < tris.Count(); t += 3)
					{
						vector p[3];
						p[0] = m_Plant.CoordToParent(tris[t]);
						p[1] = m_Plant.CoordToParent(tris[t + 1]);
						p[2] = m_Plant.CoordToParent(tris[t + 2]);
						m_aShapes.Insert(Shape.CreateTris(0xFFFF00FF, ShapeFlags.DOUBLESIDE | ShapeFlags.NOOUTLINE | ShapeFlags.FLAT | ShapeFlags.NOCULL, p, 1));
					}
					m_iStep = 5;
					m_fTimer = 0;
					m_iFrames = 0;
					return;
				}
				m_Plant.SetFlags(EntityFlags.VISIBLE, true);
				WriteRow();
				m_iShots++;
				NextView();
				return;
			}
			case 5:
			{
				if (!Settled())
					return;
				System.MakeScreenshot(path + "_t");
				m_iStep = 6;
				m_fTimer = 0;
				return;
			}
			case 6:
			{
				if (!Shot(path + "_t") && m_fTimer < 30)
					return;
				m_aShapes.Clear();
				m_Plant.SetFlags(EntityFlags.VISIBLE, true);
				WriteRow();
				m_iShots++;
				NextView();
				return;
			}
		}
	}
}
