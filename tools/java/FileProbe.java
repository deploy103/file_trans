import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

public final class FileProbe {
    private FileProbe() {
    }

    private static String jsonEscape(String value) {
        return value
            .replace("\\", "\\\\")
            .replace("\"", "\\\"")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t");
    }

    public static void main(String[] args) {
        if (args.length != 1) {
            System.err.println("usage: java FileProbe <file>");
            System.exit(2);
        }

        Path path = Path.of(args[0]);
        try {
            long size = Files.size(path);
            String name = path.getFileName() == null ? "" : path.getFileName().toString();
            System.out.printf(
                "{\"language\":\"java\",\"name\":\"%s\",\"size\":%d}%n",
                jsonEscape(name),
                size
            );
        } catch (IOException error) {
            System.err.println(error.getMessage());
            System.exit(1);
        }
    }
}
