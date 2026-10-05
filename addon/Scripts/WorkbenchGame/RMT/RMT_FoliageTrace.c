// foliagetrace: can rays measure how see-through trees and bushes are, instead of photographs?
// For up to -rmtFtPerKind plants of each common kind near the map centre, fires a grid of level rays straight through
// the plant (12 heights x 12 offsets across its box, from 3 m outside to 3 m past it) with several ray settings, and
// writes the share of rays that stop on the plant itself (or a part of it) for each setting and height band.
//   foliagetrace/rays.csv  prefab,kind,height,band,config,rays,hits
// Compare with the photo-measured cover of the same kinds (everon-data/foliage/foliage_profiles.json).
// RESEARCH ONLY, not in the pipeline and not in any user-facing job list (rmt.py runs it only when named with --jobs).
// Its answer is in: leaves are not in the collision data, so rays stop on about 18% of a plant's box, correlation 0.37
// against the photographs. Do not add more ray settings. Known flaws, left as they are: the search rings are nested
// boxes and plants have no id, so a plant is measured again on every larger ring, and the per-kind cap counts visits,
// not plants.
class RMT_FoliageTraceJob
{
	protected RMT_Context m_Ctx;
	protected ref map<string, int> m_mTaken = new map<string, int>();

	void RMT_FoliageTraceJob(RMT_Context ctx)
	{
		m_Ctx = ctx;
	}

	protected bool IsPlant(string prefab)
	{
		if (!prefab.Contains("/Vegetation/Tree/") && !prefab.Contains("/Vegetation/Bush/"))
			return false;
		string lower = prefab;
		lower.ToLower();
		return !lower.Contains("/debris/") && !lower.Contains("_stump") && !lower.Contains("_branch") && !lower.Contains("_fallen");
	}

	protected bool Owns(IEntity plant, IEntity hit)
	{
		IEntity e = hit;
		for (int i = 0; i < 4 && e; i++)
		{
			if (e == plant)
				return true;
			e = e.GetParent();
		}
		return false;
	}

	protected int HitsFor(IEntity plant, vector wmin, vector wmax, float y0, float y1, int flags, int mask, out int rays)
	{
		BaseWorld world = m_Ctx.m_World;
		float cx = (wmin[0] + wmax[0]) * 0.5;
		float halfZ = (wmax[2] - wmin[2]) * 0.5;
		int hits = 0;
		rays = 0;
		for (int iy = 0; iy < 4; iy++)
		{
			float y = y0 + (y1 - y0) * (iy + 0.5) / 4;
			for (int ix = 0; ix < 12; ix++)
			{
				float x = wmin[0] + (wmax[0] - wmin[0]) * (ix + 0.5) / 12;
				TraceParam p = new TraceParam();
				p.Start = Vector(x, y, wmin[2] - 3);
				p.End = Vector(x, y, wmax[2] + 3);
				p.Flags = flags;
				p.LayerMask = mask;
				float frac = world.TraceMove(p, null);
				rays++;
				if (frac < 1 && p.TraceEnt && Owns(plant, p.TraceEnt))
					hits++;
			}
		}
		return hits;
	}

	int Run()
	{
		float t0 = System.GetTickCount();
		string folder = m_Ctx.m_sOut + "/foliagetrace";
		RMT_Context.MakeDirs(folder);
		FileHandle f = FileIO.OpenFile(folder + "/rays.csv", FileMode.WRITE);
		if (!f)
			return 1;
		f.WriteLine("prefab,kind,height,band,config,rays,hits");
		int perKind = m_Ctx.Arg("-rmtFtPerKind", "4").ToInt();
		array<string> names = {"all", "all+visibility", "foliage", "viewgeo", "vegetation", "foliage+visibility"};
		array<int> flags = {TraceFlags.WORLD | TraceFlags.ENTS, TraceFlags.WORLD | TraceFlags.ENTS | TraceFlags.VISIBILITY,
			TraceFlags.ENTS, TraceFlags.ENTS, TraceFlags.ENTS, TraceFlags.ENTS | TraceFlags.VISIBILITY};
		array<int> masks = {0xFFFFFFFF, 0xFFFFFFFF, EPhysicsLayerDefs.Foliage, EPhysicsLayerDefs.ViewGeometry,
			EPhysicsLayerDefs.Vegetation, EPhysicsLayerDefs.Foliage};
		float cx = (m_Ctx.m_vMin[0] + m_Ctx.m_vMax[0]) * 0.5;
		float cz = (m_Ctx.m_vMin[2] + m_Ctx.m_vMax[2]) * 0.5;
		int plants = 0;
		for (int ring = 0; ring < 8; ring++)
		{
			float r0 = ring * 250;
			array<IEntity> found = m_Ctx.Query(cx - r0 - 250, cz - r0 - 250, cx + r0 + 250, cz + r0 + 250);
			foreach (IEntity e : found)
			{
				string prefab = RMT_Context.PrefabOf(e);
				if (!IsPlant(prefab) || m_mTaken.Get(prefab) >= perKind)
					continue;
				m_mTaken.Set(prefab, m_mTaken.Get(prefab) + 1);
				plants++;
				vector wmin, wmax;
				e.GetWorldBounds(wmin, wmax);
				float h = wmax[1] - wmin[1];
				string kind = "bush";
				if (prefab.Contains("/Vegetation/Tree/"))
					kind = "tree";
				// three height bands: bottom third, middle, top third of the plant
				for (int band = 0; band < 3; band++)
				{
					float y0 = wmin[1] + h * band / 3;
					float y1 = wmin[1] + h * (band + 1) / 3;
					for (int c = 0; c < names.Count(); c++)
					{
						int rays;
						int hits = HitsFor(e, wmin, wmax, y0, y1, flags[c], masks[c], rays);
						f.WriteLine(string.Format("%1,%2,%3,%4,%5,%6,%7", RMT_Context.Q(prefab), kind, h, band, names[c], rays, hits));
					}
				}
			}
		}
		f.Close();
		RMT_Context.Say(string.Format("foliagetrace|plants=%1|kinds=%2", plants, m_mTaken.Count()));
		m_Ctx.WriteStatus("foliagetrace", "done", 1, 0, 0, plants, System.GetTickCount() - t0);
		return 0;
	}
}
