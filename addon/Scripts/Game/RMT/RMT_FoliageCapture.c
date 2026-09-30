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
// The plant is turned for each side; the camera always looks north from the south, from low enough that the plant's
// base is 5 degrees above the horizon, so everything behind the plant is sky (checked: 100% of its pixels).
// Rows go to <run>/foliage/shots.csv (the old tool's columns plus `view`), so the same analysis applies. Plants whose
// last view is on disk are skipped, so a stopped run carries on. At the end: <run>/foliage.status.json, then close.

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
	protected int m_iSkipped;
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
			Say("error|foliage|no plants.csv in " + m_sOut);
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

		// the spot (rmt.py passes the empty world's middle), lifted well clear of the ground and the sea
		array<string> xz = {};
		Param("rmtFoliageSpot", "2048,2048").Split(",", xz, true);
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

		string csvPath = m_sOut + "/shots.csv";
		bool isNew = !FileIO.FileExists(csvPath);
		m_Csv = FileIO.OpenFile(csvPath, FileMode.APPEND);
		if (!m_Csv)
			return false;
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
		weather.SetTimeOfTheDay(12.0);
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
			m_fDist = Math.Min(m_fDist, m_fLift - 2);
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
			string last = m_sOut + "/" + m_aViewId[m_aViewId.Count() - 1] + "_b";
			if (!FileIO.FileExists(last + ".bmp") && !FileIO.FileExists(last + ".png"))
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
			NextPlant();
			return;
		}
		m_fBaseY = m_Plant.GetOrigin()[1];
		m_iView = 0;
		m_iStep = 0;
		m_fTimer = 0;
		GetGame().BeginPreload(GetWorld(), m_vSpot, 200);
	}

	//------------------------------------------------------------------------------------------------
	protected void Finish()
	{
		m_bDone = true;
		RemovePlant();
		if (m_Csv)
			m_Csv.Close();
		Say(string.Format("foliage|done|plants=%1|skipped=%2|shots=%3", m_aPrefab.Count(), m_iSkipped, m_iShots));
		FileHandle f = FileIO.OpenFile(Param("rmtOut") + "/foliage.status.json", FileMode.WRITE);
		if (f)
		{
			f.WriteLine(string.Format("{\"job\": \"foliage\", \"result\": \"done\", \"made\": %1, \"skipped\": %2, \"items\": %3}", m_aPrefab.Count() - m_iSkipped, m_iSkipped, m_iShots));
			f.Close();
		}
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
			FileIO.MakeDirectory(m_sOut);
			NextPlant();
			return;
		}
		m_fTimer += timeSlice;
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
					Say("error|foliage|does not fit the frame: " + m_sKey);
					NextPlant();
					return;
				}
				m_iStep = 1;
				m_fTimer = 0;
				return;
			}
			case 1:
			{
				if (m_fTimer < 0.1)
					return; // the right level of detail for the new distance loads
				System.MakeScreenshot(path + "_a");
				m_iStep = 2;
				m_fTimer = 0;
				return;
			}
			case 2:
			{
				if (m_fTimer < 0.1)
					return;
				m_Plant.ClearFlags(EntityFlags.VISIBLE, true);
				m_iStep = 3;
				m_fTimer = 0;
				return;
			}
			case 3:
			{
				if (m_fTimer < 0.1)
					return;
				System.MakeScreenshot(path + "_b");
				m_iStep = 4;
				m_fTimer = 0;
				return;
			}
			case 4:
			{
				if (m_fTimer < 0.1)
					return;
				m_Plant.SetFlags(EntityFlags.VISIBLE, true);
				WriteRow();
				m_iShots++;
				m_iView++;
				m_iStep = 0;
				m_fTimer = 0;
				if (m_iView >= m_aViewId.Count())
				{
					Say(string.Format("foliage|plant|%1|%2|left=%3", m_iPlant, m_sKey, m_aPrefab.Count() - m_iPlant - 1));
					NextPlant();
				}
				return;
			}
		}
	}
}
