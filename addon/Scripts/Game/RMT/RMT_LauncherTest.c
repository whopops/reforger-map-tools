// Live rocket launcher test through a soldier's real weapon, game side. launchertest.py starts the real game with
// -rmtLauncher 1; RMT_GameHook places this entity once the world has loaded. Unlike RMT_FireTest (which launches
// rockets directly), a soldier carrying the launcher stands on a cliff above the sea, zeroes the sight, raises the
// weapon, aims and pulls the trigger, so the rocket gets everything the game does to a shot a player fires: the
// weapon's dispersion, sway, the muzzle's spawn point and angle. It never blocks the engine: one frame event does it.
//
// What it aims: the BORE (the launcher's muzzle direction, read from the weapon manager), at the planned bearing and
// elevation, corrected (secant method, as RMT_GunTest lays a mortar) through the soldier's aiming angles until within
// AIM_OK. The sights are not aimed but recorded at the moment of firing, every way the engine reports them, so the
// score can tell how far the sight line sits from the bore at each zeroing (what the field map assumes from the
// prefabs' SightRangeInfo Angles) and which point of the PGO-7 reticle is the bore.
//
//   -rmtOut=$profile:...   run folder. Reads <out>/launcher/plan.csv, writes <out>/launcher/shots.csv, traj.csv and
//                          <out>/launchertest.status.json, then asks the game to close.
// plan.csv (header line, then one line per aim):
//   id,soldier,launcher,x,z,az,el,zero,count,wspeed,wdir,stance
//   soldier: a character prefab that carries the launcher; launcher: a launcher prefab to put in its place (the RPG-7
//   with the PGO-7 scope), or empty to keep its own; x,z: where it stands; az, el: compass bearing and elevation to
//   point the bore at (degrees); zero: the sight's range index (0 = its first mark); count: rounds, each by a fresh
//   soldier (0 = aim and record the sights only, nothing fired); wspeed, wdir: the wind (m/s, and the direction it
//   blows TOWARD, as the weather override takes it); stance: 0 standing, 1 crouched, 2 prone.
// traj.csv: id,round,t,x,y,z,vx,vy,vz: every frame of every rocket (t from when it was fired)
// shots.csv: id,round,zero,tries,mx,my,mz,bx,by,bz,sdx,sdy,sdz,stx,sty,stz,srx,sry,srz,sfx,sfy,sfz,zx,zy,zz,
//            v0x,v0y,v0z,v0dt,x,y,z,tof
//   m: the muzzle; b: the bore (unit vector); sd: BaseSightsComponent.GetSightsDirection (rear to front, world);
//   st: GetSightsTransform's forward axis (world); sr, sf: the rear and front sight points (world); z: the forward axis
//   of the weapon's GetCurrentSightsZeroingTransform (weapon space); zero: GetCurrentSightsZeroing (the range set);
//   v0: the rocket's velocity when first seen, v0dt s after firing; x,y,z: where it went off; tof: seconds flown
//   (-1 for a sights-only line); end: ground (x,y,z where it met the terrain), in_air (removed too high to reach the
//   ground: x,y,z is its last known point), lost (still flying after LOST_T s: x,y,z is where it was then), sights.
// If the planned launcher cannot be put in the soldier's hands, nothing is fired from that soldier and the job ends
// failed: a shot from the soldier's own weapon is never recorded as the planned one.

class RMT_LauncherTestEntityClass : GenericEntityClass
{
}

class RMT_LauncherTestEntity : GenericEntity
{
	protected string m_sDir;
	protected ref array<ref array<string>> m_aPlan = {};
	protected ref FileHandle m_Out;      // ref: without it the file is closed and freed under us
	protected ref FileHandle m_Trace;

	protected int m_iRow;
	protected int m_iRound;
	protected int m_iState;              // 0 settle after load, 1 spawn, 2 equip, 3 aim, 4 fire, 5 in flight, 6 done, 7 wind settle
	protected float m_fTimer;
	protected bool m_bPreloading;       // waiting for the world round the first spot to stream in
	protected float m_fStep;
	protected int m_iDone;
	protected int m_iLost;
	protected bool m_bSelectionFailed; // expected projectile identity from optional plan column
	protected string m_sFailReason;
	const float LOST_T = 15;             // s a rocket is followed
	const float IMPACT_T = 0.1;          // s past the last frame a rocket is carried on to find the ground

	protected BaseWeatherManagerEntity m_Weather;
	protected float m_fWindS = -1;
	protected float m_fWindD = -1;
	const float SETTLE = 60;             // s for the air to take a new wind

	protected IEntity m_Soldier;
	protected CharacterControllerComponent m_Ctrl;
	protected BaseWeaponManagerComponent m_Weapons;
	protected BaseWeaponComponent m_Launcher;

	// aiming: the soldier's aiming angles (radians, yaw and pitch) and per axis the commands tried and the errors seen
	protected vector m_vAim;
	protected ref array<float> m_aYawCmd = {};
	protected ref array<float> m_aYawGot = {};
	protected ref array<float> m_aPitchCmd = {};
	protected ref array<float> m_aPitchGot = {};
	protected int m_iTries;
	protected int m_iSteady;

	// the record taken as the trigger is pulled
	protected string m_sAimRec;

	// the rocket in the air
	protected IEntity m_Fired;
	protected float m_fFiredAt;
	protected bool m_bSeen;
	protected vector m_vV0;
	protected float m_fV0dt;
	protected vector m_vLast;
	protected vector m_vVel;
	protected float m_fT;

	const float EQUIP = 4;               // s for the soldier to take the launcher in hand
	const float AIM_STEP = 0.25;         // s between aiming corrections
	const float AIM_OK = 0.02;           // degrees, both axes
	const int AIM_STEADY = 4;            // corrections in a row within AIM_OK before firing
	const int AIM_MAX = 60;

	//------------------------------------------------------------------------------------------------
	protected static void Say(string msg)
	{
		Print("RMT|" + msg, LogLevel.NORMAL);
	}

	//------------------------------------------------------------------------------------------------
	protected static string F(float v)
	{
		return v.ToString(0, 5);
	}

	//------------------------------------------------------------------------------------------------
	protected static string V(vector v)
	{
		return string.Format("%1,%2,%3,", F(v[0]), F(v[1]), F(v[2]));
	}

	//------------------------------------------------------------------------------------------------
	void RMT_LauncherTestEntity(IEntitySource src, IEntity parent)
	{
		SetEventMask(EntityEvent.FRAME);
		SetFlags(EntityFlags.ACTIVE, true);
	}

	//------------------------------------------------------------------------------------------------
	protected bool Setup()
	{
		string outDir;
		System.GetCLIParam("rmtOut", outDir);
		m_sDir = outDir + "/launcher";
		FileHandle f = FileIO.OpenFile(m_sDir + "/plan.csv", FileMode.READ);
		if (!f)
		{
			m_sFailReason = "no plan " + m_sDir + "/plan.csv";
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
		if (m_aPlan.IsEmpty())
		{
			m_sFailReason = "the plan has no aims";
			return false;
		}
		m_Out = FileIO.OpenFile(m_sDir + "/shots.csv", FileMode.WRITE);
		m_Trace = FileIO.OpenFile(m_sDir + "/traj.csv", FileMode.WRITE);
		if (!m_Out || !m_Trace)
		{
			m_sFailReason = "could not open shots.csv or traj.csv in " + m_sDir;
			return false;
		}
		m_Out.WriteLine("id,round,zero,tries,mx,my,mz,bx,by,bz,sdx,sdy,sdz,stx,sty,stz,srx,sry,srz,sfx,sfy,sfz,zx,zy,zz,v0x,v0y,v0z,v0dt,x,y,z,tof,end");
		m_Trace.WriteLine("id,round,t,x,y,z,vx,vy,vz");
		m_Weather = BaseWeatherManagerEntity.Cast(WeatherManager.GetRegisteredWeatherManagerEntity(GetWorld()));
		Say(string.Format("launcher|setup|aims=%1|weather=%2", m_aPlan.Count(), m_Weather != null));
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
		Say(string.Format("launcher|wind|asked=%1 m/s %2 deg", s, d));
	}

	//------------------------------------------------------------------------------------------------
	protected void Clear()
	{
		if (m_Soldier)
			delete m_Soldier;
		m_Soldier = null;
		m_Ctrl = null;
		m_Weapons = null;
		m_Launcher = null;
	}

	//------------------------------------------------------------------------------------------------
	// the soldier, facing the planned bearing, with the planned launcher in its launcher slot
	protected bool Spawn(array<string> row)
	{
		Clear();
		Resource res = Resource.Load(row[1]);
		if (!res.IsValid())
		{
			Say("launcher|error|no soldier prefab " + row[1]);
			return false;
		}
		float x = row[3].ToFloat();
		float z = row[4].ToFloat();
		EntitySpawnParams params = new EntitySpawnParams();
		params.TransformMode = ETransformMode.WORLD;
		vector mat[4];
		Math3D.AnglesToMatrix(Vector(row[5].ToFloat(), 0, 0), mat);
		mat[3] = Vector(x, GetWorld().GetSurfaceY(x, z), z);
		params.Transform = mat;
		m_Soldier = GetGame().SpawnEntityPrefab(res, GetWorld(), params);
		if (!m_Soldier)
			return false;
		m_Ctrl = CharacterControllerComponent.Cast(m_Soldier.FindComponent(CharacterControllerComponent));
		if (!m_Ctrl)
			return false;
		m_Weapons = m_Ctrl.GetWeaponManagerComponent();
		if (!m_Weapons)
			return false;
		if (row[2] != "")
		{
			// put the planned launcher (the RPG-7 with the PGO-7) in the slot the soldier's own launcher is in
			Resource lres = Resource.Load(row[2]);
			bool swapped = false;
			array<WeaponSlotComponent> slots = {};
			m_Weapons.GetWeaponsSlots(slots);
			foreach (WeaponSlotComponent slot : slots)
			{
				IEntity w = slot.GetWeaponEntity();
				BaseWeaponComponent wc;
				if (w)
					wc = BaseWeaponComponent.Cast(w.FindComponent(BaseWeaponComponent));
				if (wc && wc.GetWeaponType() == EWeaponType.WT_ROCKETLAUNCHER && lres.IsValid())
				{
					EntitySpawnParams lp = new EntitySpawnParams();
					lp.TransformMode = ETransformMode.WORLD;
					lp.Transform = mat;
					IEntity mine = GetGame().SpawnEntityPrefab(lres, GetWorld(), lp);
					if (!mine)
						break;
					IEntity old = m_Weapons.SetSlotWeapon(slot, mine);
					swapped = slot.GetWeaponEntity() == mine;
					if (!swapped)
					{
						delete mine;
						break;
					}
					if (old && old != mine)
						delete old;
					break;
				}
			}
			if (!swapped)
			{
				// never fire the soldier's own weapon and record it as the planned one
				m_sFailReason = string.Format("%1: could not put %2 in the soldier's launcher slot", row[0], row[2]);
				Say("launcher|error|" + m_sFailReason);
				return false;
			}
		}
		int stance = row[11].ToInt();
		if (stance == 1)
			m_Ctrl.SetStanceChange(ECharacterStanceChange.STANCECHANGE_TOCROUCH);
		else if (stance == 2)
			m_Ctrl.SetStanceChange(ECharacterStanceChange.STANCECHANGE_TOPRONE);
		return true;
	}

	//------------------------------------------------------------------------------------------------
	protected bool Equip(array<string> row)
	{
		array<BaseWeaponComponent> weapons = {};
		m_Weapons.GetWeapons(weapons);
		foreach (BaseWeaponComponent w : weapons)
		{
			if (w.GetWeaponType() == EWeaponType.WT_ROCKETLAUNCHER)
				m_Launcher = w;
		}
		if (!m_Launcher)
		{
			Say("launcher|error|the soldier has no launcher");
			return false;
		}
		m_Ctrl.SelectWeapon(m_Launcher);
		SCR_MuzzleEffectComponent effects = SCR_MuzzleEffectComponent.Cast(m_Launcher.GetOwner().FindComponent(SCR_MuzzleEffectComponent));
		if (!effects)
		{
			Say("launcher|error|no muzzle effect component, so no way to see the rocket fired");
			return false;
		}
		effects.GetOnWeaponFired().Insert(OnFired);
		return true;
	}

	//------------------------------------------------------------------------------------------------
	protected void OnFired(IEntity effectEntity, BaseMuzzleComponent muzzle, IEntity projectileEntity)
	{
		if (projectileEntity && !m_Fired)
		{
			array<string> row = m_aPlan[m_iRow];
			if (row.Count() > 12 && row[12] != "")
			{
				EntityPrefabData pd = projectileEntity.GetPrefabData();
				if (!pd || pd.GetPrefabName() != row[12])
				{
					m_bSelectionFailed = true;
					Say("launcher|error|fired ammunition does not match selected projectile " + row[12]);
				}
			}
			m_Fired = projectileEntity;
			m_fFiredAt = m_fTimer;
		}
	}

	//------------------------------------------------------------------------------------------------
	protected static float Wrap(float a)
	{
		while (a > 180)
			a -= 360;
		while (a < -180)
			a += 360;
		return a;
	}

	//------------------------------------------------------------------------------------------------
	// where the bore points now: compass bearing and elevation in degrees
	protected bool Bore(out float az, out float el)
	{
		vector t[4];
		if (!m_Weapons.GetCurrentMuzzleTransform(t))
			return false;
		vector d = t[2].Normalized();
		az = Math.Atan2(d[0], d[2]) * Math.RAD2DEG;
		if (az < 0)
			az += 360;
		el = Math.Asin(d[1]) * Math.RAD2DEG;
		return true;
	}

	//------------------------------------------------------------------------------------------------
	// The next command for one axis (radians): from the last two tries, where the error will be zero (secant); with
	// one try, a small step to learn which way the command moves the bore.
	protected static float NextCommand(array<float> cmd, array<float> got)
	{
		int n = cmd.Count();
		float c1 = cmd[n - 1];
		float g1 = got[n - 1];
		if (n == 1)
			return c1 + 0.01;
		float c0 = cmd[n - 2];
		float g0 = got[n - 2];
		if (Math.AbsFloat(g1 - g0) < 0.00001)
			return c1 + 0.002;
		float next = c1 - g1 * (c1 - c0) / (g1 - g0);
		// no wild jumps from a noisy pair of readings (sway): at most 5 degrees a step
		return Math.Clamp(next, c1 - 0.087, c1 + 0.087);
	}

	//------------------------------------------------------------------------------------------------
	// hold the weapon up and in the sights, with the current aiming angles: every frame, as a player's input would
	protected void Hold()
	{
		m_Ctrl.SetWeaponRaised(true);
		m_Ctrl.SetWeaponADS(true);
		CharacterInputContext input = m_Ctrl.GetInputContext();
		if (input)
		{
			input.SetWeaponADS(true);
			input.SetAimingAngles(m_vAim);
		}
	}

	//------------------------------------------------------------------------------------------------
	// one aiming correction: true once the bore has stayed on the planned bearing and elevation (or it gave up)
	protected bool AimStep(array<string> row)
	{
		float az, el;
		if (!Bore(az, el))
			return false;
		float eAz = Wrap(az - row[5].ToFloat());
		float eEl = el - row[6].ToFloat();
		if (Math.AbsFloat(eAz) < AIM_OK && Math.AbsFloat(eEl) < AIM_OK)
		{
			m_iSteady++;
			return m_iSteady >= AIM_STEADY;
		}
		m_iSteady = 0;
		if (m_iTries >= AIM_MAX)
		{
			Say(string.Format("launcher|aim|gave up|off by %1 deg az, %2 deg el", eAz, eEl));
			return true;
		}
		m_aYawCmd.Insert(m_vAim[0]);
		m_aYawGot.Insert(eAz);
		m_aPitchCmd.Insert(m_vAim[1]);
		m_aPitchGot.Insert(eEl);
		if (Math.AbsFloat(eAz) >= AIM_OK)
			m_vAim[0] = NextCommand(m_aYawCmd, m_aYawGot);
		if (Math.AbsFloat(eEl) >= AIM_OK)
			m_vAim[1] = NextCommand(m_aPitchCmd, m_aPitchGot);
		m_iTries++;
		return false;
	}

	//------------------------------------------------------------------------------------------------
	// the bore and every reading of the sights, as the trigger is pulled
	protected string AimRecord()
	{
		vector t[4];
		m_Weapons.GetCurrentMuzzleTransform(t);
		string s = V(t[3]) + V(t[2].Normalized());
		BaseSightsComponent sights = m_Launcher.GetSights();
		vector sd, st, sr, sf, zf;
		if (sights)
		{
			sd = sights.GetSightsDirection(false, true);
			vector m[4];
			if (sights.GetSightsTransform(m, false))
				st = m[2].Normalized();
			sr = sights.GetSightsRearPosition(false);
			sf = sights.GetSightsFrontPosition(false);
		}
		vector zm[4];
		if (m_Launcher.GetCurrentSightsZeroingTransform(zm))
			zf = zm[2].Normalized();
		return s + V(sd) + V(st) + V(sr) + V(sf) + V(zf);
	}

	//------------------------------------------------------------------------------------------------
	protected void Write(array<string> row, string aimRec, vector p, string end)
	{
		string a = string.Format("%1,%2,%3,%4,", row[0], m_iRound, F(m_Launcher.GetCurrentSightsZeroing()), m_iTries);
		string c = V(m_vV0) + F(m_fV0dt) + "," + V(p) + F(m_fT) + "," + end;
		m_Out.WriteLine(a + aimRec + c);
		m_iDone++;
	}

	//------------------------------------------------------------------------------------------------
	// From the last known point along the last velocity to the terrain, at most IMPACT_T s on: a ground row, or (it
	// was removed too high to get there) an in_air row at the last known point.
	protected void WriteEnd(array<string> row)
	{
		vector p = m_vLast;
		for (float t = 0; t <= IMPACT_T; t += 0.0025)
		{
			if (p[1] <= GetWorld().GetSurfaceY(p[0], p[2]))
			{
				Write(row, m_sAimRec, p, "ground");
				return;
			}
			p = p + m_vVel * 0.0025;
		}
		Write(row, m_sAimRec, m_vLast, "in_air");
	}

	//------------------------------------------------------------------------------------------------
	protected void Finish()
	{
		m_iState = 6;
		Clear();
		if (m_Weather)
		{
			m_Weather.SetWindSpeedOverride(false);
			m_Weather.SetWindDirectionOverride(false);
		}
		if (m_Out)
			m_Out.Close();
		if (m_Trace)
			m_Trace.Close();
		Say(string.Format("launcher|done|shots=%1|lost=%2", m_iDone, m_iLost));
		string result = "done";
		string reason = m_sFailReason;
		if (m_bSelectionFailed && reason == "")
			reason = "the fired projectile was not the one planned";
		if (reason != "" || m_iDone == 0)
		{
			result = "failed";
			if (reason == "")
				reason = "no line was recorded";
		}
		else if (m_iLost > 0)
			reason = string.Format("%1 round(s) not fired", m_iLost);
		RMT_Status.Write("launchertest", result, m_iDone, m_iLost, 0, m_iDone, reason);
		GetGame().RequestClose();
	}

	//------------------------------------------------------------------------------------------------
	protected void NextRound(array<string> row)
	{
		Clear();
		m_iRound++;
		if (m_iRound >= Math.Max(1, row[8].ToInt()))
		{
			m_iRow++;
			m_iRound = 0;
		}
		m_iState = 1;
		m_fTimer = 0;
	}

	//------------------------------------------------------------------------------------------------
	override void EOnFrame(IEntity owner, float timeSlice)
	{
		if (m_iState == 6)
			return;
		m_fTimer += timeSlice;
		if (m_iState == 0)
		{
			if (m_fTimer < 10)
				return;
			if (!Setup())
			{
				Finish();
				return;
			}
			// nothing is measured until the world round the first spot has finished streaming
			float px = m_aPlan[0][3].ToFloat();
			float pz = m_aPlan[0][4].ToFloat();
			GetGame().BeginPreload(GetWorld(), Vector(px, GetWorld().GetSurfaceY(px, pz), pz), 500);
			m_bPreloading = true;
			m_iState = 1;
			m_fTimer = 0;
			return;
		}
		if (m_bPreloading)
		{
			if (!GetGame().IsPreloadFinished() && m_fTimer < 120)
				return;
			m_bPreloading = false;
			Say(string.Format("launcher|streamed|%1|after=%2 s", GetGame().IsPreloadFinished(), m_fTimer));
			m_fTimer = 0;
		}
		if (m_iState == 7)
		{
			if (m_fTimer < SETTLE)
				return;
			if (m_Weather)
				Say(string.Format("launcher|wind|settled=%1 m/s %2 deg", m_Weather.GetWindSpeed(), m_Weather.GetWindDirection()));
			else
				Say("launcher|wind|settled (no weather manager: the wind is whatever the world has)");
			m_iState = 1;
			m_fTimer = 0;
			return;
		}
		if (m_iRow >= m_aPlan.Count())
		{
			Finish();
			return;
		}
		array<string> row = m_aPlan[m_iRow];
		if (m_iState == 1)
		{
			float ws = row[9].ToFloat();
			float wd = row[10].ToFloat();
			if (ws != m_fWindS || wd != m_fWindD)
			{
				SetWind(ws, wd);
				m_iState = 7;
				m_fTimer = 0;
				return;
			}
			if (!Spawn(row))
			{
				Say(string.Format("launcher|error|%1|could not place the soldier", row[0]));
				m_iLost++;
				NextRound(row);
				return;
			}
			m_iState = 2;
			m_fTimer = 0;
			return;
		}
		if (m_iState == 2)
		{
			if (m_fTimer < 1.5)
				return;
			if (!m_Launcher && !Equip(row))
			{
				m_iLost++;
				NextRound(row);
				return;
			}
			m_Ctrl.SetSafety(false, false);
			m_Ctrl.SetSightsRange(row[7].ToInt());
			Hold();
			if (m_fTimer < 1.5 + EQUIP)
				return;
			m_aYawCmd.Clear();
			m_aYawGot.Clear();
			m_aPitchCmd.Clear();
			m_aPitchGot.Clear();
			m_vAim = vector.Zero;
			m_iTries = 0;
			m_iSteady = 0;
			m_fStep = 0;
			m_iState = 3;
			return;
		}
		if (m_iState == 3)
		{
			Hold();
			m_fStep += timeSlice;
			if (m_fStep < AIM_STEP)
				return;
			m_fStep = 0;
			if (!AimStep(row))
				return;
			m_sAimRec = AimRecord();
			m_Fired = null;
			m_bSeen = false;
			m_vV0 = vector.Zero;
			m_fV0dt = 0;
			if (row[8].ToInt() == 0)
			{
				// sights only: record where everything points, fire nothing
				m_fT = -1;
				Write(row, m_sAimRec, vector.Zero, "sights");
				Say(string.Format("launcher|sights|%1|zero %2", row[0], row[7]));
				NextRound(row);
				return;
			}
			m_iState = 4;
			m_fTimer = 0;
			return;
		}
		if (m_iState == 4)
		{
			Hold();
			m_Ctrl.SetFireWeaponWanted(true);
			if (m_Fired)
			{
				m_Ctrl.SetFireWeaponWanted(false);
				m_fT = m_fTimer - m_fFiredAt;
				m_iState = 5;
				Say(string.Format("launcher|fired|%1|%2", row[0], m_iRound));
				return;
			}
			if (m_fTimer > 5)
			{
				m_Ctrl.SetFireWeaponWanted(false);
				Say(string.Format("launcher|error|%1|%2|did not fire", row[0], m_iRound));
				m_iLost++;
				NextRound(row);
			}
			return;
		}
		if (m_iState == 5)
		{
			m_fT += timeSlice;
			if (!m_Fired)
			{
				// it went off and was removed between the last frame and this one (or burst in the air)
				if (m_bSeen)
					WriteEnd(row);
				else
					m_iLost++;
				NextRound(row);
				return;
			}
			ProjectileMoveComponent move = ProjectileMoveComponent.Cast(m_Fired.FindComponent(ProjectileMoveComponent));
			vector p = m_Fired.GetOrigin();
			if (move)
				m_vVel = move.GetVelocity();
			if (!m_bSeen && m_vVel.Length() > 1)
			{
				m_bSeen = true;
				m_vV0 = m_vVel;
				m_fV0dt = m_fT;
			}
			m_vLast = p;
			string head = string.Format("%1,%2,%3,", row[0], m_iRound, F(m_fT));
			m_Trace.WriteLine(head + V(p) + string.Format("%1,%2,%3", F(m_vVel[0]), F(m_vVel[1]), F(m_vVel[2])));
			if (m_fT > 0.3 && p[1] <= GetWorld().GetSurfaceY(p[0], p[2]) + 0.2)
			{
				WriteEnd(row);
				delete m_Fired;
				NextRound(row);
				return;
			}
			if (m_fT > LOST_T)
			{
				// still flying: where it was is recorded, marked lost, not dropped
				Say(string.Format("launcher|lost|%1|%2", row[0], m_iRound));
				Write(row, m_sAimRec, p, "lost");
				delete m_Fired;
				NextRound(row);
			}
		}
	}
}
