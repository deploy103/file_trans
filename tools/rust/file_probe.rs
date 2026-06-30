use std::env;
use std::fs;
use std::path::Path;

fn json_escape(value: &str) -> String {
    value
        .replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace('\n', "\\n")
        .replace('\r', "\\r")
        .replace('\t', "\\t")
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 2 {
        eprintln!("usage: fileprobe-rust <file>");
        std::process::exit(2);
    }

    let path = Path::new(&args[1]);
    let metadata = match fs::metadata(path) {
        Ok(value) => value,
        Err(error) => {
            eprintln!("{}", error);
            std::process::exit(1);
        }
    };
    let name = path.file_name().and_then(|value| value.to_str()).unwrap_or("");
    println!(
        "{{\"language\":\"rust\",\"name\":\"{}\",\"size\":{}}}",
        json_escape(name),
        metadata.len()
    );
}
