// ballistics/sim.csv: the engine's own mortar shell flight (ProjectileMoveComponent.GetProjectileSimulationResult, the call
// BI's wind-table generator uses) for every mortar shell and charge ring, over a grid of elevations, target heights and
// winds. A reference to test other ballistics against (e.g. the field map's mortar calculator); nothing in the world is used.
// Columns: shell prefab, ring index, speed coefficient, muzzle speed (m/s), elevation (deg), target height (m above the
// mortar), wind (none / cross = 10 m/s blowing to the right / head / tail), and where the shell ended (x right, y up,
// z downrange). When the shell never climbs to the target height, y ends below it (the run stops on time or distance).
class RMT_BallisticsJob
{
	protected RMT_Context m_Ctx;

	//------------------------------------------------------------------------------------------------
	void RMT_BallisticsJob(RMT_Context ctx)
	{
		m_Ctx = ctx;
	}

	//------------------------------------------------------------------------------------------------
	// InitSpeed of the prefab's projectile move component (as BI's SCR_ProjectileWindageDataGeneratorPlugin reads it).
	protected float InitSpeed(IEntitySource src)
	{
		for (int i, n = src.GetComponentCount(); i < n; i++)
		{
			IEntityComponentSource c = src.GetComponent(i);
			if (!c || !c.GetClassName().ToType().IsInherited(ProjectileMoveComponent))
				continue;
			float v;
			c.Get("InitSpeed", v);
			return v;
		}
		return -1;
	}

	//------------------------------------------------------------------------------------------------
	protected static string F(float v)
	{
		return v.ToString(0, 3);
	}

	//------------------------------------------------------------------------------------------------
	// Every muzzle's dispersion settings in a weapon prefab, defaults included (a Get on a container returns the class
	// default when the prefab doesn't set the value): "RMT|ballistics|muzzle|<prefab>|<class>|diameter=..|range=..".
	protected void SayMuzzles(ResourceName prefab)
	{
		Resource res = Resource.Load(prefab);
		if (!res.IsValid())
			return;
		IEntitySource src = res.GetResource().ToEntitySource();
		for (int i, n = src.GetComponentCount(); i < n; i++)
			SayMuzzle(FilePath.StripPath(prefab), src.GetComponent(i));
	}

	//------------------------------------------------------------------------------------------------
	protected void SayMuzzle(string prefab, BaseContainer c)
	{
		if (!c)
			return;
		if (c.GetClassName().ToType() && c.GetClassName().ToType().IsInherited(BaseMuzzleComponent))
		{
			float diameter, range;
			c.Get("DispersionDiameter", diameter);
			c.Get("DispersionRange", range);
			RMT_Context.Say(string.Format("ballistics|muzzle|%1|%2|diameter=%3|range=%4", prefab, c.GetClassName(), diameter, range));
		}
		BaseContainerList kids = c.GetObjectArray("components");
		if (!kids)
			return;
		for (int i, n = kids.Count(); i < n; i++)
			SayMuzzle(prefab, kids.Get(i));
	}

	//------------------------------------------------------------------------------------------------
	int Run()
	{
		SayMuzzles("{89BB7489D53FBB6C}Prefabs/Weapons/Core/Mortar_Base.et");
		SayMuzzles("{D1FFE458E8AC4BDB}Prefabs/Weapons/Mortars/2B14/Mortar_2B14.et");
		SayMuzzles("{C63227C0E70EA62E}Prefabs/Weapons/Rifles/M16/Rifle_M16A2_base.et"); // sets its diameter: a check
		float t0 = System.GetTickCount();
		string dir = m_Ctx.m_sOut + "/ballistics";
		RMT_Context.MakeDirs(dir);
		FileHandle f = FileIO.OpenFile(dir + "/sim.csv", FileMode.WRITE);
		if (!f)
			return 1;
		f.WriteLine("shell,ring,coef,v0,angle,dh,wind,x,y,z");

		array<ResourceName> shells = {
			"{38BAE094333E31BF}Prefabs/Weapons/Ammo/Ammo_Shell_81mm_HE_M821.et",
			"{DD6844AB03FDA84F}Prefabs/Weapons/Ammo/Ammo_Shell_81mm_Practice_M879.et",
			"{F7807293E94D3C88}Prefabs/Weapons/Ammo/Ammo_Shell_81mm_Smoke_M819.et",
			"{DD2065AE34D8DFA9}Prefabs/Weapons/Ammo/Ammo_Shell_81mm_Illum_M853A1.et",
			"{98EC9C526AFBA282}Prefabs/Weapons/Ammo/Ammo_Shell_82mm_HE_O832DU.et",
			"{A544A2C131DE2C64}Prefabs/Weapons/Ammo/Ammo_Shell_82mm_Smoke_D832DU.et",
			"{C8A906FB198D1A33}Prefabs/Weapons/Ammo/Ammo_Shell_82mm_Illum_S832S.et"
		};
		array<float> heights = {-200, -100, -50, -20, 0, 20, 50, 100, 200};
		array<string> windNames = {"none", "cross", "head", "tail"};
		array<vector> winds = {};
		winds.Insert(vector.Zero);
		winds.Insert(vector.Right * 10);
		winds.Insert(-vector.Forward * 10);
		winds.Insert(vector.Forward * 10);

		int rows;
		foreach (ResourceName rn : shells)
		{
			Resource res = Resource.Load(rn);
			if (!res.IsValid())
			{
				RMT_Context.Say("ballistics|error|no prefab " + rn);
				continue;
			}
			IEntitySource src = res.GetResource().ToEntitySource();
			float v0 = InitSpeed(src);
			IEntity shell = GetGame().SpawnEntityPrefab(res, m_Ctx.m_World);
			if (!shell || v0 <= 0)
			{
				RMT_Context.Say("ballistics|error|could not spawn " + rn);
				continue;
			}
			ProjectileMoveComponent move = ProjectileMoveComponent.Cast(shell.FindComponent(ProjectileMoveComponent));
			SCR_MortarShellGadgetComponent gadget = SCR_MortarShellGadgetComponent.Cast(shell.FindComponent(SCR_MortarShellGadgetComponent));
			if (!move || !gadget)
			{
				RMT_Context.Say("ballistics|error|no move or charge component on " + rn);
				delete shell;
				continue;
			}
			for (int r, nr = gadget.GetNumberOfChargeRingConfigurations(); r < nr; r++)
			{
				vector cfg = gadget.GetChargeRingConfig(r); // [ring, speed coefficient, default]
				float coef = cfg[1];
				for (int a = 40; a <= 88; a++)
				{
					foreach (float dh : heights)
					{
						foreach (int w, vector wind : winds)
						{
							vector p = move.GetProjectileSimulationResult(vector.Zero, v0 * coef, a, 0, wind, dh, true, 120, -1);
							string head = string.Format("%1,%2,%3,%4,%5,%6,%7,", FilePath.StripPath(rn), cfg[0], F(coef), F(v0), a, dh, windNames[w]);
							f.WriteLine(head + string.Format("%1,%2,%3", F(p[0]), F(p[1]), F(p[2])));
							rows++;
						}
					}
				}
				RMT_Context.Say(string.Format("ballistics|%1|ring=%2|coef=%3|rows=%4", FilePath.StripPath(rn), cfg[0], coef, rows));
			}
			delete shell;
		}
		f.Close();
		RMT_Context.Say(string.Format("ballistics|done|rows=%1|ms=%2", rows, System.GetTickCount() - t0));
		string result = "done";
		if (rows == 0)
			result = "failed";
		m_Ctx.WriteStatus("ballistics", result, 1, 0, 0, rows, System.GetTickCount() - t0);
		if (rows == 0)
			return 1;
		return 0;
	}
}
