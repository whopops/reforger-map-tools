// When the real game is started by rmt.py with -rmtSat (satellite pictures), -rmtFoliage (plant photographs),
// -rmtFire (live mortar firing test), -rmtGun (mortar through the real weapon), -rmtBlast (live mortar blast test) or
// -rmtLauncher (live rocket launcher test), place that job's entity as soon as the world is loaded. Without any of the
// flags this does nothing. One job per game process: with more than one flag nothing is spawned, a failed status is
// written for each named job (so rmt.py stops waiting and does not store a result), and the game is asked to close.
// The jobs themselves wait for the world around their first spot to finish streaming (GetGame().BeginPreload /
// IsPreloadFinished) before the first measured spawn or shot.
modded class ArmaReforgerScripted
{
	override void OnWorldPostProcess(World world)
	{
		super.OnWorldPostProcess(world);
		array<string> flags = {"rmtSat", "rmtFire", "rmtGun", "rmtBlast", "rmtLauncher", "rmtFoliage"};
		array<string> jobs = {"satellite", "firetest", "guntest", "blasttest", "launchertest", "foliage"};
		array<int> given = {};
		string flag;
		foreach (int i, string f : flags)
		{
			if (System.GetCLIParam(f, flag))
				given.Insert(i);
		}
		if (given.IsEmpty())
			return;
		if (given.Count() > 1)
		{
			string names = "";
			foreach (int j : given)
				names += " -" + flags[j];
			string reason = "more than one job flag:" + names + " (one job per game process)";
			foreach (int k : given)
				RMT_Status.Write(jobs[k], "failed", 0, 0, 1, 0, reason);
			Print("RMT|hook|refused|" + reason, LogLevel.ERROR);
			GetGame().RequestClose();
			return;
		}
		EntitySpawnParams params = new EntitySpawnParams();
		params.TransformMode = ETransformMode.WORLD;
		int which = given[0];
		IEntity e;
		if (which == 0)
			e = SpawnEntity(RMT_SatCaptureEntity, world, params);
		else if (which == 1)
			e = SpawnEntity(RMT_FireTestEntity, world, params);
		else if (which == 2)
			e = SpawnEntity(RMT_GunTestEntity, world, params);
		else if (which == 3)
			e = SpawnEntity(RMT_BlastTestEntity, world, params);
		else if (which == 4)
			e = SpawnEntity(RMT_LauncherTestEntity, world, params);
		else
			e = SpawnEntity(RMT_FoliageCaptureEntity, world, params);
		Print(string.Format("RMT|%1|hook|spawned=%2", jobs[which], e != null), LogLevel.NORMAL);
		if (!e)
		{
			RMT_Status.Write(jobs[which], "failed", 0, 0, 1, 0, "the job's entity could not be spawned");
			GetGame().RequestClose();
		}
	}
}
