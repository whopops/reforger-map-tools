// Chunked jobs. Formats match the old Everon exporter (arma-map/everon-map/tools/workbench), so its bakers and
// the everon-data export can be used to check these.

//------------------------------------------------------------------------------------------------
// terrain/t_TX_TZ.csv: header "x0,z0,step,cols,rows", then one row per line from south to north, west to east,
// heights in integer centimetres (GetSurfaceY, the ground without objects). The last row and column repeat the
// next chunk's first, so chunks overlap by one sample.
class RMT_TerrainJob : RMT_ChunkJob
{
	protected float m_fStep;

	void RMT_TerrainJob(RMT_Context ctx, string name, string folder, string prefix)
	{
		m_fStep = ctx.Arg("-rmtStep", "1").ToFloat();
		if (m_fStep < 0.25)
			m_fStep = 0.25;
	}

	override protected bool WriteChunk(int tx, int tz, string path)
	{
		FileHandle f = FileIO.OpenFile(path, FileMode.WRITE);
		if (!f)
			return false;
		float x0 = m_Ctx.ChunkX(tx);
		float z0 = m_Ctx.ChunkZ(tz);
		int per = Math.Round(m_Ctx.m_fTile / m_fStep);
		f.Write(string.Format("%1,%2,%3,%4,%5\n", x0, z0, m_fStep, per + 1, per + 1));
		BaseWorld world = m_Ctx.m_World;
		for (int r = 0; r <= per; r++)
		{
			float z = z0 + r * m_fStep;
			string line = "";
			for (int c = 0; c <= per; c++)
			{
				int cm = Math.Round(world.GetSurfaceY(x0 + c * m_fStep, z) * 100);
				if (c > 0)
					line += ",";
				line += cm.ToString();
			}
			f.Write(line + "\n");
		}
		f.Close();
		m_iItems += (per + 1) * (per + 1);
		return true;
	}
}

//------------------------------------------------------------------------------------------------
// objects/o_TX_TZ.csv: every entity whose origin is in the chunk (so each appears once), except engine helpers.
//   class,prefab,x,y,z,yaw,pitch,roll,scale,minx,miny,minz,maxx,maxy,maxz,parent,lminx,lminy,lminz,lmaxx,lmaxy,lmaxz
// min/max is the world axis-aligned box; lmin/lmax is the entity's own box before rotation (for oriented
// footprints); parent is the parent entity's prefab (or class) if it has one.
class RMT_EntitiesJob : RMT_ChunkJob
{
	override protected bool WriteChunk(int tx, int tz, string path)
	{
		float x0 = m_Ctx.ChunkX(tx);
		float z0 = m_Ctx.ChunkZ(tz);
		float x1 = x0 + m_Ctx.m_fTile;
		float z1 = z0 + m_Ctx.m_fTile;
		array<IEntity> found = m_Ctx.Query(x0, z0, x1, z1);
		FileHandle f = FileIO.OpenFile(path, FileMode.WRITE);
		if (!f)
			return false;
		f.Write("class,prefab,x,y,z,yaw,pitch,roll,scale,minx,miny,minz,maxx,maxy,maxz,parent,lminx,lminy,lminz,lmaxx,lmaxy,lmaxz\n");
		foreach (IEntity e : found)
		{
			vector o = e.GetOrigin();
			if (o[0] < x0 || o[0] >= x1 || o[2] < z0 || o[2] >= z1 || RMT_Context.Skippable(e))
				continue;
			vector wmin, wmax, lmin, lmax;
			e.GetWorldBounds(wmin, wmax);
			e.GetBounds(lmin, lmax);
			vector ypr = e.GetYawPitchRoll();
			string parent = "";
			IEntity pe = e.GetParent();
			if (pe)
			{
				parent = RMT_Context.PrefabOf(pe);
				if (parent == "")
					parent = pe.ClassName();
			}
			string line = string.Format("%1,%2,%3,%4,%5,%6,%7,%8,", RMT_Context.Q(e.ClassName()), RMT_Context.Q(RMT_Context.PrefabOf(e)), o[0], o[1], o[2], ypr[0], ypr[1], ypr[2]);
			line += string.Format("%1,%2,%3,%4,%5,%6,%7,", e.GetScale(), wmin[0], wmin[1], wmin[2], wmax[0], wmax[1], wmax[2]);
			line += RMT_Context.Q(parent) + ",";
			line += string.Format("%1,%2,%3,%4,%5,%6\n", lmin[0], lmin[1], lmin[2], lmax[0], lmax[1], lmax[2]);
			f.Write(line);
			m_iItems++;
		}
		f.Close();
		return true;
	}
}

//------------------------------------------------------------------------------------------------
// surface/s_TX_TZ.csv: rays over every spot an object covers (same as the old "Island: surfaces").
// Header "x0,z0,step,cols,rows", then sparse lines "col,row,top,bottom,kind,cover", heights in decimetres above
// the ground. kind 1 building, 2 other solid, 3 vegetation. Unlisted cells are open ground or water.
class RMT_SurfaceJob : RMT_ChunkJob
{
	protected float m_fStep;
	protected ref array<int> m_aOcc = {};

	void RMT_SurfaceJob(RMT_Context ctx, string name, string folder, string prefix)
	{
		m_fStep = ctx.Arg("-rmtStep", "0.5").ToFloat();
		if (m_fStep < 0.25)
			m_fStep = 0.25;
	}

	protected int HitKind(IEntity hit)
	{
		if (!hit)
			return 0;
		string cls = hit.ClassName();
		if (cls == "Tree")
			return 3;
		if (cls.Contains("Lake") || cls.Contains("Ocean") || cls.Contains("Terrain") || cls.Contains("River"))
			return 0;
		if (cls.Contains("Building"))
			return 1;
		return 2;
	}

	protected float Trace(vector from, vector to, int mask, out IEntity hit)
	{
		TraceParam p = new TraceParam();
		p.Start = from;
		p.End = to;
		p.Flags = TraceFlags.WORLD | TraceFlags.ENTS;
		p.LayerMask = mask;
		float frac = m_Ctx.m_World.TraceMove(p, null);
		hit = p.TraceEnt;
		return frac;
	}

	override protected bool WriteChunk(int tx, int tz, string path)
	{
		float x0 = m_Ctx.ChunkX(tx);
		float z0 = m_Ctx.ChunkZ(tz);
		int per = Math.Round(m_Ctx.m_fTile / m_fStep);
		m_aOcc.Resize(per * per);
		for (int i = 0; i < per * per; i++)
			m_aOcc[i] = 0;
		// Mark the cells any object's footprint covers (objects reaching in from the next chunk included).
		array<IEntity> found = m_Ctx.Query(x0 - 50, z0 - 50, x0 + m_Ctx.m_fTile + 50, z0 + m_Ctx.m_fTile + 50);
		foreach (IEntity e : found)
		{
			if (RMT_Context.Skippable(e))
				continue;
			vector wmin, wmax;
			e.GetWorldBounds(wmin, wmax);
			int c0 = Math.Max(0, Math.Floor((wmin[0] - x0) / m_fStep));
			int c1 = Math.Min(per - 1, Math.Floor((wmax[0] - x0) / m_fStep));
			int r0 = Math.Max(0, Math.Floor((wmin[2] - z0) / m_fStep));
			int r1 = Math.Min(per - 1, Math.Floor((wmax[2] - z0) / m_fStep));
			for (int rr = r0; rr <= r1; rr++)
			{
				for (int cc = c0; cc <= c1; cc++)
					m_aOcc[rr * per + cc] = 1;
			}
		}
		FileHandle f = FileIO.OpenFile(path, FileMode.WRITE);
		if (!f)
			return false;
		f.Write(string.Format("%1,%2,%3,%4,%5\n", x0, z0, m_fStep, per, per));
		BaseWorld world = m_Ctx.m_World;
		for (int r = 0; r < per; r++)
		{
			string block = "";
			for (int c = 0; c < per; c++)
			{
				if (m_aOcc[r * per + c] == 0)
					continue;
				float x = x0 + (c + 0.5) * m_fStep;
				float z = z0 + (r + 0.5) * m_fStep;
				float g = world.GetSurfaceY(x, z);
				IEntity hit;
				float frac = Trace(Vector(x, g + 150, z), Vector(x, g - 1, z), 0xFFFFFFFF, hit);
				float top = 151 * (1 - frac) - 1;
				int kind = HitKind(hit);
				if (kind == 0 || top < 0.2)
					continue;
				float bottom = 0;
				if (kind == 3)
				{
					IEntity up;
					float fu = Trace(Vector(x, g + 0.3, z), Vector(x, g + top + 0.5, z), 0xFFFFFFFF, up);
					if (fu < 1)
						bottom = 0.3 + (top + 0.2) * fu;
					else
						bottom = top;
				}
				IEntity bhit;
				float fb = Trace(Vector(x, g + 150, z), Vector(x, g - 1, z), EPhysicsLayerPresets.Projectile, bhit);
				float cover = 151 * (1 - fb) - 1;
				if (HitKind(bhit) == 0 || cover < 0.2)
					cover = 0;
				int topDm = Math.Round(top * 10);
				int botDm = Math.Round(bottom * 10);
				int covDm = Math.Round(cover * 10);
				block += string.Format("%1,%2,%3,%4,%5,%6\n", c, r, topDm, botDm, kind, covDm);
				m_iItems++;
			}
			if (block != "")
				f.Write(block);
		}
		f.Close();
		return true;
	}
}
