import { execFileSync } from "node:child_process";
import path from "node:path";

export default function teardown() {
  execFileSync("uv", ["run", "python", path.resolve(__dirname, "prepare.py"), "down"], {
    cwd: path.resolve(__dirname, "../../../services/api"), stdio: "inherit",
  });
}
