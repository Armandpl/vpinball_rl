# /// script
# requires-python = ">=3.10"
# dependencies = ["olefile>=0.47", "extract-msg>=0.55", "pycryptodome>=3.20"]
# ///
"""Instrument a locally supplied Big Brave v601: uv run vprl/build_big_brave.py."""
import argparse
from pathlib import Path
import runpy

# Load authoring helpers without importing the runtime package (numpy).
helpers = runpy.run_path(str(Path(__file__).with_name("build_table.py")))
ROOT = helpers["ROOT"]


def build(source):
    base = helpers["load"](source)
    if helpers["table_mac"](base) != base["GameStg/MAC"]:
        raise ValueError("Source integrity calculation differs from VPX")
    for field, expected in (("TableName", "Big Brave (Maresa 1974)"),
                            ("AuthorName", "jpsalas"), ("TableVersion", "6.0.1")):
        if base.get("TableInfo/" + field, b"").decode("utf-16le") != expected:
            raise ValueError(f"Unexpected source {field}; expected {expected}")
    script = helpers["script_from"](base)
    if "Sub RLObserve" in script or "Function RLObserve" in script:
        raise ValueError("Table is already instrumented")
    script += "\n" + (ROOT / "vprl/big_brave_hooks.vbs").read_text()
    streams = base.copy()
    streams["GameStg/GameData"] = helpers["patch"](
        base["GameStg/GameData"], {b"CODE": script.encode("cp1252")}, offset=0)
    streams["GameStg/MAC"] = helpers["table_mac"](streams)
    output = ROOT / "vprl/assets/big_brave.vpx"
    output.parent.mkdir(parents=True, exist_ok=True)
    writer = helpers["OleWriter"]()
    with helpers["olefile"].OleFileIO(source) as original:
        writer.fromOleFile(original)
    for path, data in streams.items():
        if data != base[path]:
            writer.editEntry(path, data=data)
    writer.write(output)
    print(f"Wrote {output}")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", type=Path,
                        default=ROOT / "Big Brave (Maresa 1974) v601.vpx")
    build(parser.parse_args().source)
