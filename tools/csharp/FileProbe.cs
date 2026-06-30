using System;
using System.IO;

public static class FileProbe
{
    private static string JsonEscape(string value)
    {
        return value
            .Replace("\\", "\\\\")
            .Replace("\"", "\\\"")
            .Replace("\n", "\\n")
            .Replace("\r", "\\r")
            .Replace("\t", "\\t");
    }

    public static int Main(string[] args)
    {
        if (args.Length != 1)
        {
            Console.Error.WriteLine("usage: mono fileprobe-cs.exe <file>");
            return 2;
        }

        try
        {
            var info = new FileInfo(args[0]);
            Console.WriteLine(
                "{{\"language\":\"csharp\",\"name\":\"{0}\",\"size\":{1}}}",
                JsonEscape(info.Name),
                info.Length
            );
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error.Message);
            return 1;
        }
    }
}
