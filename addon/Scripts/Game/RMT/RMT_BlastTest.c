// Live mortar blast test, game side. blasttest.py starts the real game on EmptyEden (Everon's terrain with nothing
// standing on it, so no tree, wall or building blocks a fragment) with -rmtBlast 1; RMT_GameHook places this entity once
// the world has loaded. For each trial it stands a ring of soldiers (the game's own rifleman prefab, no AI) around an
// impact point, drops a real mortar shell onto that point at the planned angle, waits for the explosion to do its work,
// and writes what happened to every soldier. It never blocks the engine: one frame event does everything.
//
//   -rmtOut=$profile:...   run folder. Reads <out>/blast/plan.csv and layout.csv, writes <out>/blast/hits.csv,
//                          bursts.csv and <out>/blasttest.status.json, then asks the game to close.
// plan.csv (header line, then one line per trial): id,prefab,soldier,x,z,az,descent,stance,uncon
//   prefab: the shell; soldier: the character prefab; x,z: where the shell is aimed; az: compass bearing it travels
//   along (degrees); descent: degrees below the horizon it comes down at; stance: 0 standing, 1 crouched, 2 prone;
//   uncon: 1 if a soldier can be knocked unconscious (as most servers have it), 0 if not (damage that would knock
//   him out kills him).
// layout.csv (header line, then one line per soldier): along,across (m from the aim point; along = the way the shell
//   travels). The same layout is used for every trial, turned to its bearing.
// bursts.csv: id,x,y,z,ground (where the shell went off, and the ground there)
// hits.csv: id,n,x,y,z,stance,life,state,health,bleeding,min_zone
//   life: ECharacterLifeState as a number, 0 alive, 1 incapacitated (unconscious), 10 dead (the engine's values; its
//   generated script lists the names only); state: the damage state (2 destroyed); health: the character's
//   overall health (0-1); min_zone: the lowest health of any of its hit zones (0-1)

class RMT_BlastTestEntityClass : GenericEntityClass
{
}

class RMT_BlastTestEntity : GenericEntity
{
	protected string m_sDir;
	protected ref array<ref array<string>> m_aPlan = {};
	protected ref array<vector> m_aLayout = {};
	protected ref array<IEntity> m_aSoldiers = {};
	protected ref FileHandle m_Hits;     // ref: without it the file is closed and freed under us
	protected ref FileHandle m_Bursts;

	protected int m_iRow;
	protected int m_iState;              // 0 settle after load, 1 place soldiers, 2 let them settle, 3 shell flying, 4 after the burst, 5 done
	protected float m_fTimer;
	protected IEntity m_Shell;
	protected vector m_vShellLast;
	protected vector m_vBurst;
	protected vector m_vDir;
	protected int m_iDone;
	protected int m_iFailed;

	const float START = 60;              // m back along its path the shell starts from (the fuze arms after 30 m:
	                                     // SafetyDistance in Prefabs/Weapons/Core/Ammo_MortarShell_Base.et)
	const float SETTLE = 4;              // s for the soldiers to stand (or get down) before the shell comes
	const float AFTER = 2;               // s after the burst before reading the soldiers (before bleeding can kill)

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
	void RMT_BlastTestEntity(IEntitySource src, IEntity parent)
	{
		SetEventMask(EntityEvent.FRAME);
		SetFlags(EntityFlags.ACTIVE, true);
	}

	//------------------------------------------------------------------------------------------------
	protected bool ReadCsv(string path, int minCols, notnull array<ref array<string>> rows)
	{
		FileHandle f = FileIO.OpenFile(path, FileMode.READ);
		if (!f)
		{
			Say("blast|error|no file " + path);
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
			if (cols.Count() >= minCols)
				rows.Insert(cols);
		}
		f.Close();
		return true;
	}

	//------------------------------------------------------------------------------------------------
	protected bool Setup()
	{
		string outDir;
		System.GetCLIParam("rmtOut", outDir);
		m_sDir = outDir + "/blast";
		if (!ReadCsv(m_sDir + "/plan.csv", 9, m_aPlan))
			return false;
		array<ref array<string>> layout = {};
		if (!ReadCsv(m_sDir + "/layout.csv", 2, layout))
			return false;
		foreach (array<string> l : layout)
		{
			m_aLayout.Insert(Vector(l[0].ToFloat(), 0, l[1].ToFloat()));
		}
		m_Hits = FileIO.OpenFile(m_sDir + "/hits.csv", FileMode.WRITE);
		m_Bursts = FileIO.OpenFile(m_sDir + "/bursts.csv", FileMode.WRITE);
		if (!m_Hits || !m_Bursts)
			return false;
		m_Hits.WriteLine("id,n,x,y,z,stance,life,state,health,bleeding,min_zone");
		m_Bursts.WriteLine("id,x,y,z,ground");
		Say(string.Format("blast|setup|trials=%1|soldiers=%2", m_aPlan.Count(), m_aLayout.Count()));
		return true;
	}

	//------------------------------------------------------------------------------------------------
	// along/across on bearing az (degrees) to world x, z
	protected static vector Turn(vector p, float az)
	{
		float a = az * Math.DEG2RAD;
		float s = Math.Sin(a);
		float c = Math.Cos(a);
		return Vector(p[0] * s + p[2] * c, 0, p[0] * c - p[2] * s);
	}

	//------------------------------------------------------------------------------------------------
	protected void PlaceSoldiers(array<string> row)
	{
		Resource res = Resource.Load(row[2]);
		if (!res.IsValid())
		{
			Say("blast|error|no soldier prefab " + row[2]);
			return;
		}
		float x = row[3].ToFloat();
		float z = row[4].ToFloat();
		float az = row[5].ToFloat();
		int stance = row[7].ToInt();
		bool uncon = row[8].ToInt() == 1;
		foreach (vector l : m_aLayout)
		{
			vector off = Turn(l, az);
			float px = x + off[0];
			float pz = z + off[2];
			EntitySpawnParams params = new EntitySpawnParams();
			params.TransformMode = ETransformMode.WORLD;
			vector mat[4];
			Math3D.AnglesToMatrix(Vector(Math.RandomFloat(0, 360), 0, 0), mat);
			mat[3] = Vector(px, GetWorld().GetSurfaceY(px, pz), pz);
			params.Transform = mat;
			IEntity soldier = GetGame().SpawnEntityPrefab(res, GetWorld(), params);
			m_aSoldiers.Insert(soldier);
			if (!soldier)
				continue;
			SCR_CharacterDamageManagerComponent dmg = SCR_CharacterDamageManagerComponent.Cast(soldier.FindComponent(SCR_CharacterDamageManagerComponent));
			if (dmg)
				dmg.SetPermitUnconsciousness(uncon, false);
			CharacterControllerComponent ctrl = CharacterControllerComponent.Cast(soldier.FindComponent(CharacterControllerComponent));
			if (ctrl && stance == 1)
				ctrl.SetStanceChange(ECharacterStanceChange.STANCECHANGE_TOCROUCH);
			else if (ctrl && stance == 2)
				ctrl.SetStanceChange(ECharacterStanceChange.STANCECHANGE_TOPRONE);
		}
	}

	//------------------------------------------------------------------------------------------------
	protected bool FireShell(array<string> row)
	{
		Resource res = Resource.Load(row[1]);
		if (!res.IsValid())
		{
			Say("blast|error|no shell prefab " + row[1]);
			return false;
		}
		float x = row[3].ToFloat();
		float z = row[4].ToFloat();
		float az = row[5].ToFloat() * Math.DEG2RAD;
		float de = row[6].ToFloat() * Math.DEG2RAD;
		// travelling along az and down at the descent angle
		vector dir = Vector(Math.Sin(az) * Math.Cos(de), -Math.Sin(de), Math.Cos(az) * Math.Cos(de));
		vector aim = Vector(x, GetWorld().GetSurfaceY(x, z), z);
		vector start = aim - dir * START;
		EntitySpawnParams params = new EntitySpawnParams();
		params.TransformMode = ETransformMode.WORLD;
		vector mat[4];
		Math3D.DirectionAndUpMatrix(dir, vector.Up, mat);
		mat[3] = start;
		params.Transform = mat;
		m_Shell = GetGame().SpawnEntityPrefab(res, GetWorld(), params);
		if (!m_Shell)
			return false;
		ProjectileMoveComponent move = ProjectileMoveComponent.Cast(m_Shell.FindComponent(ProjectileMoveComponent));
		if (!move)
		{
			delete m_Shell;
			return false;
		}
		move.Launch(dir, vector.Zero, 1, m_Shell, null, null, null, null);
		m_vShellLast = start;
		m_vDir = dir;
		return true;
	}

	//------------------------------------------------------------------------------------------------
	protected void Record(array<string> row)
	{
		string id = row[0];
		float g = GetWorld().GetSurfaceY(m_vBurst[0], m_vBurst[2]);
		m_Bursts.WriteLine(string.Format("%1,%2,%3,%4,%5", id, F(m_vBurst[0]), F(m_vBurst[1]), F(m_vBurst[2]), F(g)));
		foreach (int n, IEntity s : m_aSoldiers)
		{
			if (!s)
				continue;
			vector p = s.GetOrigin();
			int life = -1;
			int stance = -1;
			CharacterControllerComponent ctrl = CharacterControllerComponent.Cast(s.FindComponent(CharacterControllerComponent));
			if (ctrl)
			{
				life = ctrl.GetLifeState();
				stance = ctrl.GetStance();
			}
			int state = -1;
			float health = -1;
			int bleeding = 0;
			float minZone = 1;
			SCR_CharacterDamageManagerComponent dmg = SCR_CharacterDamageManagerComponent.Cast(s.FindComponent(SCR_CharacterDamageManagerComponent));
			if (dmg)
			{
				state = dmg.GetState();
				health = dmg.GetHealthScaled();
				if (dmg.IsBleeding())
					bleeding = 1;
				array<HitZone> zones = {};
				dmg.GetAllHitZones(zones);
				foreach (HitZone hz : zones)
				{
					if (hz.GetMaxHealth() > 0)
						minZone = Math.Min(minZone, hz.GetHealthScaled());
				}
			}
			string a = string.Format("%1,%2,%3,%4,%5,%6,", id, n, F(p[0]), F(p[1]), F(p[2]), stance);
			m_Hits.WriteLine(a + string.Format("%1,%2,%3,%4,%5", life, state, F(health), bleeding, F(minZone)));
		}
	}

	//------------------------------------------------------------------------------------------------
	// Items lying about (rifles and kit the soldiers dropped): gathered by QueryEntitiesBySphere, removed by Clear
	protected ref array<IEntity> m_aLoose = {};
	protected bool AddLoose(IEntity e)
	{
		if (e && e.FindComponent(InventoryItemComponent))
			m_aLoose.Insert(e);
		return true;
	}

	//------------------------------------------------------------------------------------------------
	// The soldiers, and whatever they dropped: the spots are used again, and a rifle on the ground stops fragments
	protected void Clear()
	{
		foreach (IEntity s : m_aSoldiers)
		{
			if (s)
				delete s;
		}
		m_aSoldiers.Clear();
		if (m_iRow < m_aPlan.Count())
		{
			array<string> row = m_aPlan[m_iRow];
			vector c = Vector(row[3].ToFloat(), 0, row[4].ToFloat());
			c[1] = GetWorld().GetSurfaceY(c[0], c[2]);
			m_aLoose.Clear();
			GetWorld().QueryEntitiesBySphere(c, 100, AddLoose, null, EQueryEntitiesFlags.ALL);
			foreach (IEntity e : m_aLoose)
			{
				if (e && !e.GetParent())
					delete e;
			}
			m_aLoose.Clear();
		}
	}

	//------------------------------------------------------------------------------------------------
	protected void Finish()
	{
		m_iState = 5;
		Clear();
		if (m_Hits)
			m_Hits.Close();
		if (m_Bursts)
			m_Bursts.Close();
		Say(string.Format("blast|done|trials=%1|failed=%2", m_iDone, m_iFailed));
		string outDir;
		System.GetCLIParam("rmtOut", outDir);
		FileHandle f = FileIO.OpenFile(outDir + "/blasttest.status.json", FileMode.WRITE);
		if (f)
		{
			f.WriteLine(string.Format("{\"job\": \"blasttest\", \"result\": \"done\", \"made\": %1, \"skipped\": %2, \"items\": %3}", m_iDone, m_iFailed, m_iDone));
			f.Close();
		}
		GetGame().RequestClose();
	}

	//------------------------------------------------------------------------------------------------
	override void EOnFrame(IEntity owner, float timeSlice)
	{
		if (m_iState == 5)
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
			m_iState = 1;
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
			PlaceSoldiers(row);
			m_iState = 2;
			m_fTimer = 0;
			return;
		}
		if (m_iState == 2)
		{
			if (m_fTimer < SETTLE)
				return;
			if (!FireShell(row))
			{
				m_iFailed++;
				Clear();
				m_iRow++;
				m_iState = 1;
				return;
			}
			m_iState = 3;
			m_fTimer = 0;
			return;
		}
		if (m_iState == 3)
		{
			if (m_Shell)
			{
				m_vShellLast = m_Shell.GetOrigin();
				if (m_fTimer < 10)
					return;
				Say("blast|lost|" + row[0]);
				delete m_Shell;
				m_iFailed++;
				Clear();
				m_iRow++;
				m_iState = 1;
				return;
			}
			// it went off and was removed: the burst is where its path from the last point it was seen meets the ground
			// (it moves a few metres a frame)
			m_vBurst = m_vShellLast;
			for (int i = 0; i < 2000 && m_vBurst[1] > GetWorld().GetSurfaceY(m_vBurst[0], m_vBurst[2]); i++)
			{
				m_vBurst = m_vBurst + m_vDir * 0.005;
			}
			m_iState = 4;
			m_fTimer = 0;
			return;
		}
		if (m_iState == 4)
		{
			if (m_fTimer < AFTER)
				return;
			Record(row);
			Clear();
			m_iDone++;
			if (m_iDone % 10 == 0)
				Say(string.Format("blast|trial|%1|left=%2", row[0], m_aPlan.Count() - m_iRow - 1));
			m_iRow++;
			m_iState = 1;
		}
	}
}
