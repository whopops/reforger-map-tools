// The status file every game-side job writes at the end, <rmtOut>/<job>.status.json (rmt.py's runner watches for it
// there to know the job finished). One contract for every job:
//   done     every output the job claims exists, is not empty, and holds the rows it says
//   partial  a declared incomplete output that is still usable; remaining (> 0) says how much is missing
//   failed   do not bake it, and run it again next time; reason says why
// A setup that failed (no plan, no output folder, a file that would not open, a spawn that did not happen) is failed,
// never done.
class RMT_Status
{
	//------------------------------------------------------------------------------------------------
	static string Out()
	{
		string dir;
		System.GetCLIParam("rmtOut", dir);
		return dir;
	}

	//------------------------------------------------------------------------------------------------
	// Size of a file in bytes, -1 if it is not there or cannot be opened.
	static int FileSize(string path)
	{
		if (!FileIO.FileExists(path))
			return -1;
		FileHandle f = FileIO.OpenFile(path, FileMode.READ);
		if (!f)
			return -1;
		int n = f.GetLength();
		f.Close();
		return n;
	}

	//------------------------------------------------------------------------------------------------
	static string Esc(string s)
	{
		string t = s;
		t.Replace("\\", "\\\\");
		t.Replace("\"", "\\\"");
		return t;
	}

	//------------------------------------------------------------------------------------------------
	// Writes <rmtOut>/<job>.status.json. extra: more JSON members, already formatted ("\"k\": 1, ").
	static bool Write(string job, string result, int made, int skipped, int remaining, int items, string reason = "", string extra = "")
	{
		FileHandle f = FileIO.OpenFile(Out() + "/" + job + ".status.json", FileMode.WRITE);
		if (!f)
			return false;
		string line = string.Format("{\"job\": \"%1\", \"result\": \"%2\", \"made\": %3, \"skipped\": %4, \"remaining\": %5, ", job, result, made, skipped, remaining);
		line += string.Format("\"items\": %1, %2\"reason\": \"%3\"}", items, extra, Esc(reason));
		f.WriteLine(line);
		f.Close();
		Print(string.Format("RMT|status|%1|%2|%3", job, result, reason), LogLevel.NORMAL);
		return true;
	}
}
