// When the real game is started by rmt.py with -rmtSat (satellite pictures), -rmtFoliage (plant photographs) or
// -rmtFire (live mortar firing test), -rmtBlast (live mortar blast test),
// place the capture entity as soon as the world is loaded. Without either flag this does nothing.
modded class ArmaReforgerScripted
{
	override void OnWorldPostProcess(World world)
	{
		super.OnWorldPostProcess(world);
		string flag;
		EntitySpawnParams params = new EntitySpawnParams();
		params.TransformMode = ETransformMode.WORLD;
		if (System.GetCLIParam("rmtSat", flag))
		{
			IEntity capture = SpawnEntity(RMT_SatCaptureEntity, world, params);
			Print(string.Format("RMT|sat|hook|capture=%1", capture != null), LogLevel.NORMAL);
		}
		if (System.GetCLIParam("rmtFire", flag))
		{
			IEntity fire = SpawnEntity(RMT_FireTestEntity, world, params);
			Print(string.Format("RMT|fire|hook|test=%1", fire != null), LogLevel.NORMAL);
		}
		if (System.GetCLIParam("rmtGun", flag))
		{
			IEntity gun = SpawnEntity(RMT_GunTestEntity, world, params);
			Print(string.Format("RMT|gun|hook|test=%1", gun != null), LogLevel.NORMAL);
		}
		if (System.GetCLIParam("rmtBlast", flag))
		{
			IEntity blast = SpawnEntity(RMT_BlastTestEntity, world, params);
			Print(string.Format("RMT|blast|hook|test=%1", blast != null), LogLevel.NORMAL);
		}
		if (System.GetCLIParam("rmtFoliage", flag))
		{
			IEntity foliage = SpawnEntity(RMT_FoliageCaptureEntity, world, params);
			Print(string.Format("RMT|foliage|hook|capture=%1", foliage != null), LogLevel.NORMAL);
		}
	}
}
