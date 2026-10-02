// Live mortar firing test, game side. rmt.py starts the real game on a world with -rmtFire 1; RMT_GameHook places this
// entity once the world has loaded. It fires real mortar shells (the way BI's Game Master artillery module launches them:
// spawn the shell prefab, point it, ProjectileMoveComponent.Launch) through the game's own physics, weather and terrain,
// follows each shell until it lands, and writes where. It never blocks the engine: one frame event does everything.
//
//   -rmtOut=$profile:...   run folder. Reads <out>/firetest/plan.csv, writes <out>/firetest/shots.csv, traj.csv and
//                          <out>/firetest.status.json, then asks the game to close.
//   -rmtFireSettle=<s>     how long a new wind is left to settle before firing (default 60: the air the shells fly
//                          through changes some time after the weather manager reports the new wind)
//   -rmtFireGap=<s>        a fixed pause between rounds (a crew re-laying and loading after each), instead of a random
//                          GAP_MIN-GAP_MAX
// plan.csv (header line, then one line per aim): id,prefab,coef,x,z,az,elev,wspeed,wdir,count,tx,tz
//   prefab: the shell's resource name; coef: its charge ring's speed coefficient; x,z: the mortar (it fires from 1.3 m
//   above the ground there, where the M252's muzzle is); az: compass bearing in degrees; elev: degrees above the
//   horizon; wspeed, wdir: wind for the weather manager's override (m/s, and the engine's direction in degrees; the
//   game's map shows this direction + 180); count: rounds to fire; tx,tz: the target, only to report its ground height.
//   Aims whose id starts with T also have every frame of every round's flight written to traj.csv.
// Lines with the same wind should be together: the wind is changed only when no shell is in the air.
// shots.csv: id,round,x0,y0,z0,x,y,z,tof,ground_mortar,ground_target,wind_speed,wind_dir,v0x,v0y,v0z
//   (v0: the round's velocity just after launch, which includes the game's random speed variation)
// traj.csv: id,round,t,x,y,z,vx,vy,vz

class RMT_FireTestEntityClass : GenericEntityClass
{
}

class RMT_FireShot
{
	int m_iPlan;
	int m_iRound;
	IEntity m_Shell;
	ProjectileMoveComponent m_Move;
	vector m_vStart;
	vector m_vLast;
	vector m_vVel;
	vector m_vV0;
	bool m_bTrace;
	float m_fT;
}

class RMT_FireTestEntity : GenericEntity
{
	protected string m_sDir;
	protected ref array<ref array<string>> m_aPlan = {};
	protected ref array<ref RMT_FireShot> m_aFlying = {};
	protected ref FileHandle m_Out;    // ref: without it the file is closed and freed under us
	protected ref FileHandle m_Trace;
	protected BaseWeatherManagerEntity m_Weather;

	protected int m_iRow;           // plan line being fired
	protected int m_iRound;         // rounds of it fired so far
	protected float m_fTimer;
	protected float m_fWindS = -1;
	protected float m_fWindD = -1;
	protected float m_fSettle = 60;
	protected int m_iState;         // 0 settle after load, 1 firing, 2 waiting for the wind, 3 done
	protected int m_iLanded;
	protected int m_iLost;

	const float MUZZLE = 1.3;       // m above the ground the shell leaves from
	// s between rounds, picked at random each time: the game's "random" launch speed drifts smoothly with game time
	// (rounds 0.25 s apart came out about 0.22 m/s apart, in steady steps), so evenly spaced rounds share their speed error
	// and an aim's rounds land long or short together
	const float GAP_MIN = 0.4;
	const float GAP_MAX = 3;
	protected float m_fGap = 1;
	protected float m_fFixedGap = -1;   // -rmtFireGap: every gap this long instead
	const int MAX_FLYING = 40;

	//------------------------------------------------------------------------------------------------
	protected static void Say(string msg)
	{
		Print("RMT|" + msg, LogLevel.NORMAL);
	}

	//------------------------------------------------------------------------------------------------
	protected static string F(float v)
	{
		return v.ToString(0, 3);
	}

	//------------------------------------------------------------------------------------------------
	void RMT_FireTestEntity(IEntitySource src, IEntity parent)
	{
		SetEventMask(EntityEvent.FRAME);
		SetFlags(EntityFlags.ACTIVE, true);
	}

	//------------------------------------------------------------------------------------------------
	protected bool Setup()
	{
		string outDir;
		System.GetCLIParam("rmtOut", outDir);
		m_sDir = outDir + "/firetest";
		string settle;
		if (System.GetCLIParam("rmtFireSettle", settle) && settle != "")
			m_fSettle = settle.ToFloat();
		string gap;
		if (System.GetCLIParam("rmtFireGap", gap) && gap != "")
			m_fFixedGap = gap.ToFloat();
		FileHandle f = FileIO.OpenFile(m_sDir + "/plan.csv", FileMode.READ);
		if (!f)
		{
			Say("fire|error|no plan " + m_sDir + "/plan.csv");
			return false;
		}
		string line;
		bool header = true;
		while (f.ReadLine(line) >= 0)
		{
			if (header)
			{
				header = false;
				continue;
			}
			array<string> cols = {};
			line.Split(",", cols, false);
			if (cols.Count() >= 12)
				m_aPlan.Insert(cols);
		}
		f.Close();
		m_Out = FileIO.OpenFile(m_sDir + "/shots.csv", FileMode.WRITE);
		m_Trace = FileIO.OpenFile(m_sDir + "/traj.csv", FileMode.WRITE);
		if (!m_Out || !m_Trace)
			return false;
		m_Out.WriteLine("id,round,x0,y0,z0,x,y,z,tof,ground_mortar,ground_target,wind_speed,wind_dir,v0x,v0y,v0z");
		m_Trace.WriteLine("id,round,t,x,y,z,vx,vy,vz");
		m_Weather = BaseWeatherManagerEntity.Cast(WeatherManager.GetRegisteredWeatherManagerEntity(GetWorld()));
		Say(string.Format("fire|setup|aims=%1|weather=%2|settle=%3", m_aPlan.Count(), m_Weather != null, m_fSettle));
		return true;
	}

	//------------------------------------------------------------------------------------------------
	protected void SetWind(float s, float d)
	{
		m_fWindS = s;
		m_fWindD = d;
		if (!m_Weather)
			return;
		m_Weather.SetWindSpeedOverride(true, s);
		m_Weather.SetWindDirectionOverride(true, d);
		Say(string.Format("fire|wind|asked=%1 m/s %2 deg|now=%3 m/s %4 deg", s, d, m_Weather.GetWindSpeed(), m_Weather.GetWindDirection()));
	}

	//------------------------------------------------------------------------------------------------
	protected void FireOne(array<string> row)
	{
		Resource res = Resource.Load(row[1]);
		if (!res.IsValid())
		{
			Say("fire|error|no prefab " + row[1]);
			m_iLost++;
			return;
		}
		float x = row[3].ToFloat();
		float z = row[4].ToFloat();
		float az = row[5].ToFloat() * Math.DEG2RAD;
		float el = row[6].ToFloat() * Math.DEG2RAD;
		vector dir = Vector(Math.Sin(az) * Math.Cos(el), Math.Sin(el), Math.Cos(az) * Math.Cos(el));
		vector start = Vector(x, GetWorld().GetSurfaceY(x, z) + MUZZLE, z);

		EntitySpawnParams params = new EntitySpawnParams();
		params.TransformMode = ETransformMode.WORLD;
		vector mat[4];
		Math3D.DirectionAndUpMatrix(dir, vector.Up, mat);
		mat[3] = start;
		params.Transform = mat;
		IEntity shell = GetGame().SpawnEntityPrefab(res, GetWorld(), params);
		if (!shell)
		{
			m_iLost++;
			return;
		}
		ProjectileMoveComponent move = ProjectileMoveComponent.Cast(shell.FindComponent(ProjectileMoveComponent));
		if (!move)
		{
			delete shell;
			m_iLost++;
			return;
		}
		// The shell's own charge rings set its speed (a fresh shell has its default rings, full charge), and Launch's
		// coefficient multiplies on top of that, like a muzzle's. So the rings go on the shell, and the launch adds nothing.
		move.SetBulletCoef(row[2].ToFloat());
		move.Launch(dir, vector.Zero, 1, shell, null, null, null, null);
		RMT_FireShot s = new RMT_FireShot();
		s.m_iPlan = m_iRow;
		s.m_iRound = m_iRound;
		s.m_Shell = shell;
		s.m_Move = move;
		s.m_vStart = start;
		s.m_vLast = start;
		s.m_vVel = dir;
		s.m_vV0 = move.GetVelocity();
		s.m_bTrace = row[0].StartsWith("T");
		m_aFlying.Insert(s);
	}

	//------------------------------------------------------------------------------------------------
	// Where the shell met the ground: from its last known point, along its last velocity, to the terrain.
	protected vector Impact(RMT_FireShot s)
	{
		vector p = s.m_vLast;
		vector v = s.m_vVel;
		for (int i = 0; i < 200; i++)
		{
			if (p[1] <= GetWorld().GetSurfaceY(p[0], p[2]))
				break;
			p = p + v * 0.005;
		}
		return p;
	}

	//------------------------------------------------------------------------------------------------
	protected void Land(RMT_FireShot s, vector p)
	{
		array<string> row = m_aPlan[s.m_iPlan];
		float gm = GetWorld().GetSurfaceY(row[3].ToFloat(), row[4].ToFloat());
		float gt = GetWorld().GetSurfaceY(row[10].ToFloat(), row[11].ToFloat());
		string a = string.Format("%1,%2,%3,%4,%5,", row[0], s.m_iRound, F(s.m_vStart[0]), F(s.m_vStart[1]), F(s.m_vStart[2]));
		string b = string.Format("%1,%2,%3,%4,", F(p[0]), F(p[1]), F(p[2]), F(s.m_fT));
		string c = string.Format("%1,%2,%3,%4,", F(gm), F(gt), F(m_fWindS), F(m_fWindD));
		string d = string.Format("%1,%2,%3", F(s.m_vV0[0]), F(s.m_vV0[1]), F(s.m_vV0[2]));
		m_Out.WriteLine(a + b + c + d);
		m_iLanded++;
	}

	//------------------------------------------------------------------------------------------------
	protected void Track(float dt)
	{
		for (int i = m_aFlying.Count() - 1; i >= 0; i--)
		{
			RMT_FireShot s = m_aFlying[i];
			s.m_fT += dt;
			if (!s.m_Shell)
			{
				// the round went off and was removed: it landed between the last frame and this one
				Land(s, Impact(s));
				m_aFlying.Remove(i);
				continue;
			}
			vector p = s.m_Shell.GetOrigin();
			if (s.m_Move)
				s.m_vVel = s.m_Move.GetVelocity();
			if (s.m_bTrace)
			{
				string head = string.Format("%1,%2,%3,", m_aPlan[s.m_iPlan][0], s.m_iRound, F(s.m_fT));
				m_Trace.WriteLine(head + string.Format("%1,%2,%3,%4,%5,%6", F(p[0]), F(p[1]), F(p[2]), F(s.m_vVel[0]), F(s.m_vVel[1]), F(s.m_vVel[2])));
			}
			if (s.m_fT > 0.5 && p[1] <= GetWorld().GetSurfaceY(p[0], p[2]) + 0.2)
			{
				s.m_vLast = p;
				Land(s, Impact(s));
				delete s.m_Shell;
				m_aFlying.Remove(i);
				continue;
			}
			s.m_vLast = p;
			if (s.m_fT > 90)
			{
				Say(string.Format("fire|lost|%1|%2", m_aPlan[s.m_iPlan][0], s.m_iRound));
				delete s.m_Shell;
				m_aFlying.Remove(i);
				m_iLost++;
			}
		}
	}

	//------------------------------------------------------------------------------------------------
	protected void Finish()
	{
		m_iState = 3;
		if (m_Out)
			m_Out.Close();
		if (m_Trace)
			m_Trace.Close();
		if (m_Weather)
		{
			m_Weather.SetWindSpeedOverride(false);
			m_Weather.SetWindDirectionOverride(false);
		}
		Say(string.Format("fire|done|landed=%1|lost=%2", m_iLanded, m_iLost));
		string outDir;
		System.GetCLIParam("rmtOut", outDir);
		FileHandle f = FileIO.OpenFile(outDir + "/firetest.status.json", FileMode.WRITE);
		if (f)
		{
			f.WriteLine(string.Format("{\"job\": \"firetest\", \"result\": \"done\", \"made\": %1, \"skipped\": %2, \"items\": %3}", m_iLanded, m_iLost, m_iLanded));
			f.Close();
		}
		GetGame().RequestClose();
	}

	//------------------------------------------------------------------------------------------------
	override void EOnFrame(IEntity owner, float timeSlice)
	{
		if (m_iState == 3)
			return;
		m_fTimer += timeSlice;
		Track(timeSlice);
		if (m_iState == 0)
		{
			if (m_fTimer < 10)
				return;
			if (!Setup())
			{
				Finish();
				return;
			}
			m_iState = 1;
			m_fTimer = 0;
			return;
		}
		if (m_iRow >= m_aPlan.Count())
		{
			if (m_aFlying.IsEmpty())
				Finish();
			return;
		}
		array<string> row = m_aPlan[m_iRow];
		float ws = row[7].ToFloat();
		float wd = row[8].ToFloat();
		if (ws != m_fWindS || wd != m_fWindD)
		{
			// change the wind only with nothing in the air, then let it settle
			if (!m_aFlying.IsEmpty())
				return;
			SetWind(ws, wd);
			m_iState = 2;
			m_fTimer = 0;
			return;
		}
		if (m_iState == 2)
		{
			if (m_fTimer < m_fSettle)
				return;
			Say(string.Format("fire|wind|settled=%1 m/s %2 deg", m_Weather.GetWindSpeed(), m_Weather.GetWindDirection()));
			m_iState = 1;
		}
		if (m_fTimer < m_fGap || m_aFlying.Count() >= MAX_FLYING)
			return;
		m_fTimer = 0;
		if (m_fFixedGap > 0)
			m_fGap = m_fFixedGap;
		else
			m_fGap = Math.RandomFloat(GAP_MIN, GAP_MAX);
		FireOne(row);
		m_iRound++;
		if (m_iRound >= row[9].ToInt())
		{
			Say(string.Format("fire|aim|%1|left=%2|flying=%3", row[0], m_aPlan.Count() - m_iRow - 1, m_aFlying.Count()));
			m_iRow++;
			m_iRound = 0;
		}
	}
}
