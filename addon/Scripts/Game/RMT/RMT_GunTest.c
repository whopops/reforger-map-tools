// Live mortar test through the real weapon, game side. firetest.py gun starts the real game with -rmtGun 1;
// RMT_GameHook places this entity once the world has loaded. Unlike RMT_FireTest (which launches shells directly, the
// way the Game Master artillery does), this places a real mortar, loads a shell with the planned charge ring into its
// barrel and fires it through the weapon, so the round gets everything the game does to a round a crew fires: the
// barrel's dispersion included. The wind is held at nothing (and given SETTLE s to take), as RMT_FireTest does for its
// no-wind aims. It never blocks the engine: one frame event does everything.
//
// Laying: with no player or AI on the gun its tube stays in its rest position (a gunner placed in the seat doesn't move
// it either, and the turret ignores aiming commands without one). So the whole mortar is turned and tilted until the
// barrel itself points along the planned bearing and elevation, read back from the barrel and corrected (secant method)
// to within LAY_OK, before every round, as a crew re-lays after the recoil. The game's dispersion is applied relative to
// the barrel, so tilting the gun instead of raising the tube doesn't change what's measured.
//
//   -rmtOut=$profile:...   run folder. Reads <out>/gun/plan.csv, writes <out>/gun/shots.csv and <out>/guntest.status.json,
//                          then asks the game to close.
// plan.csv (header line, then one line per aim): id,mortar,shell,ring,x,z,az,elev,count,tx,tz,gap[,track]
//   mortar, shell: prefabs; ring: the charge ring (the shell's charge ring configuration of that many rings); x,z: where
//   the mortar stands; az: compass bearing to lay on (degrees); elev: degrees above the horizon; count: rounds; tx,tz:
//   the target (to report its ground height); gap: seconds from one round landing to laying for the next; track: 0 to
//   record only how the round left the muzzle and remove it straight away (tof -1), 1 (or left out) to follow it down.
//   Lines for the same gun in the same place reuse it.
// traj.csv: id,round,t,x,y,z,vx,vy,vz: every frame of every round followed down (t from when it was fired)
// shots.csv: id,round,lay_az,lay_el,lay_tries,mx,my,mz,bx,by,bz,v0x,v0y,v0z,v0dt,x,y,z,tof,ground_target
//   lay_az, lay_el: where the barrel pointed when it fired (degrees); lay_tries: corrections it took; m: the muzzle;
//   b: the barrel's direction (unit vector); v0: the shell's velocity when first seen, v0dt seconds after it was fired
//   (gravity has acted that long); x,y,z: where it landed; tof: seconds in the air.

class RMT_GunTestEntityClass : GenericEntityClass
{
}

class RMT_GunTestEntity : GenericEntity
{
	protected string m_sDir;
	protected ref array<ref array<string>> m_aPlan = {};
	protected ref FileHandle m_Out;      // ref: without it the file is closed and freed under us
	protected ref FileHandle m_Trace;    // every frame of every round followed down

	protected int m_iRow;
	protected int m_iRound;
	protected int m_iState;              // 0 settle after load, 7 let the wind settle, 1 place the mortar, 2 lay, 3 fire, 4 in flight, 5 gap, 6 done
	protected float m_fTimer;
	protected int m_iDone;
	protected int m_iLost;

	protected BaseWeatherManagerEntity m_Weather;
	const float SETTLE = 60;             // s for the air the shells fly through to take the new (no) wind
	protected IEntity m_Mortar;
	protected string m_sPlaced;          // which gun stands where (prefab|x|z), so lines for the same gun reuse it
	protected vector m_vBase;            // where the mortar stands
	protected TurretControllerComponent m_Turret;
	protected BaseWeaponManagerComponent m_Weapons;

	// laying: the mortar's yaw and pitch (degrees), and per axis the commands tried and what the barrel did
	protected float m_fYaw;
	protected float m_fPitch;
	protected ref array<float> m_aYawCmd = {};
	protected ref array<float> m_aYawGot = {};
	protected ref array<float> m_aPitchCmd = {};
	protected ref array<float> m_aPitchGot = {};
	protected int m_iTries;
	protected float m_fLayAz;
	protected float m_fLayEl;
	protected vector m_vMuzzle;
	protected vector m_vBarrel;

	// the round in the air
	protected IEntity m_Shell;
	protected IEntity m_Fired;
	protected float m_fFiredAt;
	protected bool m_bSeen;
	protected vector m_vV0;
	protected float m_fV0dt;
	protected vector m_vLast;
	protected vector m_vVel;
	protected float m_fT;

	const float LAY_WAIT = 0.5;          // s after turning the gun before reading the barrel again
	const float LAY_OK = 0.003;          // degrees: about 0.05 mil, both axes
	const int LAY_MAX = 15;

	//------------------------------------------------------------------------------------------------
	protected static void Say(string msg)
	{
		Print("RMT|" + msg, LogLevel.NORMAL);
	}

	//------------------------------------------------------------------------------------------------
	protected static string F(float v)
	{
		return v.ToString(0, 4);
	}

	//------------------------------------------------------------------------------------------------
	void RMT_GunTestEntity(IEntitySource src, IEntity parent)
	{
		SetEventMask(EntityEvent.FRAME);
		SetFlags(EntityFlags.ACTIVE, true);
	}

	//------------------------------------------------------------------------------------------------
	protected bool Setup()
	{
		string outDir;
		System.GetCLIParam("rmtOut", outDir);
		m_sDir = outDir + "/gun";
		FileHandle f = FileIO.OpenFile(m_sDir + "/plan.csv", FileMode.READ);
		if (!f)
		{
			Say("gun|error|no plan " + m_sDir + "/plan.csv");
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
		if (!m_Out)
			return false;
		m_Out.WriteLine("id,round,lay_az,lay_el,lay_tries,mx,my,mz,bx,by,bz,v0x,v0y,v0z,v0dt,x,y,z,tof,ground_target");
		m_Trace = FileIO.OpenFile(m_sDir + "/traj.csv", FileMode.WRITE);
		if (m_Trace)
			m_Trace.WriteLine("id,round,t,x,y,z,vx,vy,vz");
		// no wind: the world's own weather would push the rounds (RMT_FireTest does the same, then lets it settle)
		m_Weather = BaseWeatherManagerEntity.Cast(WeatherManager.GetRegisteredWeatherManagerEntity(GetWorld()));
		if (m_Weather)
		{
			m_Weather.SetWindSpeedOverride(true, 0);
			m_Weather.SetWindDirectionOverride(true, 0);
		}
		Say(string.Format("gun|setup|aims=%1|weather=%2", m_aPlan.Count(), m_Weather != null));
		return true;
	}

	//------------------------------------------------------------------------------------------------
	protected bool PlaceMortar(array<string> row)
	{
		if (m_Mortar)
			delete m_Mortar;
		Resource res = Resource.Load(row[1]);
		if (!res.IsValid())
		{
			Say("gun|error|no mortar prefab " + row[1]);
			return false;
		}
		float x = row[4].ToFloat();
		float z = row[5].ToFloat();
		m_vBase = Vector(x, GetWorld().GetSurfaceY(x, z), z);
		EntitySpawnParams params = new EntitySpawnParams();
		params.TransformMode = ETransformMode.WORLD;
		vector mat[4];
		Math3D.AnglesToMatrix(Vector(row[6].ToFloat(), 0, 0), mat);
		mat[3] = m_vBase;
		params.Transform = mat;
		m_Mortar = GetGame().SpawnEntityPrefab(res, GetWorld(), params);
		if (!m_Mortar)
			return false;
		m_Turret = TurretControllerComponent.Cast(m_Mortar.FindComponent(TurretControllerComponent));
		if (!m_Turret)
		{
			Say("gun|error|no turret controller");
			return false;
		}
		m_Weapons = m_Turret.GetWeaponManager();
		BaseWeaponComponent weapon;
		if (m_Weapons)
			weapon = m_Weapons.GetCurrentWeapon();
		if (!weapon)
		{
			Say("gun|error|no weapon");
			return false;
		}
		SCR_MuzzleEffectComponent effects = SCR_MuzzleEffectComponent.Cast(weapon.GetOwner().FindComponent(SCR_MuzzleEffectComponent));
		if (!effects)
		{
			Say("gun|error|no muzzle effect component, so no way to see the round fired");
			return false;
		}
		effects.GetOnWeaponFired().Insert(OnFired);
		m_fYaw = row[6].ToFloat();
		m_fPitch = 0;
		return true;
	}

	//------------------------------------------------------------------------------------------------
	protected void OnFired(IEntity effectEntity, BaseMuzzleComponent muzzle, IEntity projectileEntity)
	{
		if (projectileEntity)
		{
			m_Fired = projectileEntity;
			m_fFiredAt = m_fTimer;
		}
	}

	//------------------------------------------------------------------------------------------------
	// turn and tilt the whole mortar (yaw about the vertical, then pitch), standing where it was placed
	protected void Turn()
	{
		vector mat[4];
		Math3D.AnglesToMatrix(Vector(m_fYaw, m_fPitch, 0), mat);
		mat[3] = m_vBase;
		m_Mortar.SetWorldTransform(mat);
		m_Mortar.Update();
	}

	//------------------------------------------------------------------------------------------------
	// where the barrel points now: compass bearing and elevation in degrees, and the muzzle
	protected bool Barrel(out float az, out float el)
	{
		vector t[4];
		if (!m_Weapons.GetCurrentMuzzleTransform(t))
			return false;
		vector d = t[2].Normalized();
		az = Math.Atan2(d[0], d[2]) * Math.RAD2DEG;
		if (az < 0)
			az += 360;
		el = Math.Asin(d[1]) * Math.RAD2DEG;
		m_vMuzzle = t[3];
		m_vBarrel = d;
		return true;
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
	// The next command for one axis: from the last two tries, where the barrel will be on target (secant);
	// with only one try, a small step to learn which way the command moves it.
	protected static float NextCommand(array<float> cmd, array<float> got, float want)
	{
		int n = cmd.Count();
		float c1 = cmd[n - 1];
		float g1 = got[n - 1];
		if (n == 1)
			return c1 + 1;
		float c0 = cmd[n - 2];
		float g0 = got[n - 2];
		if (Math.AbsFloat(g1 - g0) < 0.00001)
			return c1 + 0.01;
		return c1 + (want - g1) * (c1 - c0) / (g1 - g0);
	}

	//------------------------------------------------------------------------------------------------
	protected void StartLay()
	{
		m_aYawCmd.Clear();
		m_aYawGot.Clear();
		m_aPitchCmd.Clear();
		m_aPitchGot.Clear();
		m_iTries = 0;
		Turn();
		m_iState = 2;
		m_fTimer = 0;
	}

	//------------------------------------------------------------------------------------------------
	// one step of laying: true when the barrel is on the planned elevation and azimuth (or it gave up trying)
	protected bool LayStep(array<string> row)
	{
		float az, el;
		if (!Barrel(az, el))
			return false;
		float wantAz = row[6].ToFloat();
		float wantEl = row[7].ToFloat();
		float eAz = Wrap(az - wantAz);
		float eEl = el - wantEl;
		m_fLayAz = az;
		m_fLayEl = el;
		if ((Math.AbsFloat(eAz) < LAY_OK && Math.AbsFloat(eEl) < LAY_OK) || m_iTries >= LAY_MAX)
		{
			if (m_iTries >= LAY_MAX)
				Say(string.Format("gun|lay|gave up|off by %1 deg az, %2 deg el", eAz, eEl));
			return true;
		}
		m_aYawCmd.Insert(m_fYaw);
		m_aYawGot.Insert(eAz);
		m_aPitchCmd.Insert(m_fPitch);
		m_aPitchGot.Insert(eEl);
		if (Math.AbsFloat(eAz) >= LAY_OK)
			m_fYaw = NextCommand(m_aYawCmd, m_aYawGot, 0);
		if (Math.AbsFloat(eEl) >= LAY_OK)
			m_fPitch = NextCommand(m_aPitchCmd, m_aPitchGot, 0);
		Turn();
		m_iTries++;
		return false;
	}

	//------------------------------------------------------------------------------------------------
	protected bool Load(array<string> row)
	{
		Resource res = Resource.Load(row[2]);
		if (!res.IsValid())
		{
			Say("gun|error|no shell prefab " + row[2]);
			return false;
		}
		EntitySpawnParams params = new EntitySpawnParams();
		params.TransformMode = ETransformMode.WORLD;
		vector mat[4];
		Math3D.MatrixIdentity4(mat);
		mat[3] = m_vBase + Vector(2, 0.5, 0);
		params.Transform = mat;
		m_Shell = GetGame().SpawnEntityPrefab(res, GetWorld(), params);
		if (!m_Shell)
			return false;
		// the charge: the shell's configuration with that many rings
		SCR_MortarShellGadgetComponent gadget = SCR_MortarShellGadgetComponent.Cast(m_Shell.FindComponent(SCR_MortarShellGadgetComponent));
		int rings = row[3].ToInt();
		bool charged = false;
		if (gadget)
		{
			for (int i = 0; i < gadget.GetNumberOfChargeRingConfigurations(); i++)
			{
				if (Math.Round(gadget.GetChargeRingConfig(i)[0]) == rings)
				{
					gadget.SetChargeRingConfig(i, true, false);
					charged = true;
				}
			}
		}
		if (!charged)
			Say(string.Format("gun|warn|no %1-ring charge on this shell", rings));
		// into the barrel (the weapon's attachment storage, where a crew's drop puts it). The weapon may fire the moment
		// the shell is in, so the fired-callback's record is cleared first.
		m_Fired = null;
		m_bSeen = false;
		m_fT = 0;
		BaseWeaponComponent weapon = m_Weapons.GetCurrentWeapon();
		SCR_WeaponAttachmentsStorageComponent barrel = SCR_WeaponAttachmentsStorageComponent.Cast(weapon.GetOwner().FindComponent(SCR_WeaponAttachmentsStorageComponent));
		InventoryStorageManagerComponent inv = m_Turret.GetInventoryManager();
		bool loaded = false;
		if (barrel && inv)
			loaded = inv.TryInsertItemInStorage(m_Shell, barrel);
		if (!loaded)
			loaded = m_Turret.DoReloadWeaponWith(m_Shell);
		if (!loaded)
		{
			Say("gun|error|could not load the shell");
			delete m_Shell;
			return false;
		}
		return true;
	}

	//------------------------------------------------------------------------------------------------
	protected void Land(array<string> row, vector p)
	{
		float gt = GetWorld().GetSurfaceY(row[9].ToFloat(), row[10].ToFloat());
		string a = string.Format("%1,%2,%3,%4,%5,", row[0], m_iRound, F(m_fLayAz), F(m_fLayEl), m_iTries);
		string b = string.Format("%1,%2,%3,%4,%5,%6,", F(m_vMuzzle[0]), F(m_vMuzzle[1]), F(m_vMuzzle[2]), F(m_vBarrel[0]), F(m_vBarrel[1]), F(m_vBarrel[2]));
		string c = string.Format("%1,%2,%3,%4,", F(m_vV0[0]), F(m_vV0[1]), F(m_vV0[2]), F(m_fV0dt));
		string d = string.Format("%1,%2,%3,%4,%5", F(p[0]), F(p[1]), F(p[2]), F(m_fT), F(gt));
		m_Out.WriteLine(a + b + c + d);
		m_iDone++;
		if (m_fT >= 0)
			Say(string.Format("gun|landed|%1|%2", row[0], m_iRound));
	}

	//------------------------------------------------------------------------------------------------
	// where the shell met the ground: from its last known point, along its last velocity, to the terrain
	protected vector Impact()
	{
		vector p = m_vLast;
		for (int i = 0; i < 4000 && p[1] > GetWorld().GetSurfaceY(p[0], p[2]); i++)
		{
			p = p + m_vVel * 0.0025;
		}
		return p;
	}

	//------------------------------------------------------------------------------------------------
	protected void Finish()
	{
		m_iState = 6;
		if (m_Weather)
		{
			m_Weather.SetWindSpeedOverride(false);
			m_Weather.SetWindDirectionOverride(false);
		}
		if (m_Out)
			m_Out.Close();
		if (m_Trace)
			m_Trace.Close();
		Say(string.Format("gun|done|landed=%1|lost=%2", m_iDone, m_iLost));
		string outDir;
		System.GetCLIParam("rmtOut", outDir);
		FileHandle f = FileIO.OpenFile(outDir + "/guntest.status.json", FileMode.WRITE);
		if (f)
		{
			f.WriteLine(string.Format("{\"job\": \"guntest\", \"result\": \"done\", \"made\": %1, \"skipped\": %2, \"items\": %3}", m_iDone, m_iLost, m_iDone));
			f.Close();
		}
		GetGame().RequestClose();
	}

	//------------------------------------------------------------------------------------------------
	protected void NextRound(array<string> row)
	{
		m_iRound++;
		if (m_iRound >= row[8].ToInt())
		{
			m_iRow++;
			m_iRound = 0;
			m_iState = 1;
		}
		else
		{
			m_iState = 5;
		}
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
			m_iState = 7;
			m_fTimer = 0;
			return;
		}
		if (m_iState == 7)
		{
			if (m_fTimer < SETTLE)
				return;
			if (m_Weather)
				Say(string.Format("gun|wind|settled=%1 m/s", m_Weather.GetWindSpeed()));
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
			// the same gun in the same place as the last line: keep it, it's only laid again
			string where = row[1] + "|" + row[4] + "|" + row[5];
			if (m_Mortar && where == m_sPlaced)
			{
				m_iState = 5;
				m_fTimer = 0;
				return;
			}
			if (!PlaceMortar(row))
			{
				m_iLost += row[8].ToInt();
				m_iRow++;
				return;
			}
			m_sPlaced = where;
			Say(string.Format("gun|aim|%1|placed", row[0]));
			m_iState = 5;
			m_fTimer = -3;   // a moment for it to settle
			return;
		}
		if (m_iState == 5)
		{
			if (m_fTimer < row[11].ToFloat())
				return;
			StartLay();
			return;
		}
		if (m_iState == 2)
		{
			// the gun is turned only when the lay changes (StartLay, LayStep): moving it every frame floods the
			// network buffer (the game stopped on 'BitBuffer memory overflow' after about 140 rounds)
			if (m_fTimer < LAY_WAIT)
				return;
			m_fTimer = 0;
			if (!LayStep(row))
				return;
			if (!Load(row))
			{
				m_iLost++;
				NextRound(row);
				return;
			}
			m_iState = 3;
			return;
		}
		if (m_iState == 3)
		{
			// fire: hold the trigger until the shell leaves (a crew's drop fires by itself; this covers either way)
			m_Turret.SetFireWeaponWanted(true);
			if (m_Fired)
			{
				m_Turret.SetFireWeaponWanted(false);
				m_iState = 4;
				m_fT = m_fTimer - m_fFiredAt;
				return;
			}
			if (m_fTimer > 6)
			{
				m_Turret.SetFireWeaponWanted(false);
				Say(string.Format("gun|error|%1|%2|did not fire", row[0], m_iRound));
				if (m_Shell)
					delete m_Shell;
				m_iLost++;
				NextRound(row);
			}
			return;
		}
		if (m_iState == 4)
		{
			m_fT += timeSlice;
			if (!m_Fired)
			{
				// it went off and was removed: it landed between the last frame and this one
				if (m_bSeen)
					Land(row, Impact());
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
				// launch only: what the round left the muzzle with is all this line wants (tof -1, x,y,z where it was)
				if (row.Count() > 12 && row[12].ToInt() == 0)
				{
					m_fT = -1;
					Land(row, p);
					delete m_Fired;
					NextRound(row);
					return;
				}
			}
			m_vLast = p;
			if (m_Trace)
			{
				string head = string.Format("%1,%2,%3,", row[0], m_iRound, F(m_fT));
				m_Trace.WriteLine(head + string.Format("%1,%2,%3,%4,%5,%6", F(p[0]), F(p[1]), F(p[2]), F(m_vVel[0]), F(m_vVel[1]), F(m_vVel[2])));
			}
			if (m_fT > 0.5 && p[1] <= GetWorld().GetSurfaceY(p[0], p[2]) + 0.2)
			{
				Land(row, Impact());
				delete m_Fired;
				NextRound(row);
				return;
			}
			if (m_fT > 120)
			{
				Say(string.Format("gun|lost|%1|%2", row[0], m_iRound));
				delete m_Fired;
				m_iLost++;
				NextRound(row);
			}
		}
	}
}
