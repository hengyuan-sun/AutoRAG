"""对冻结源码应用可复现的Go桥接，不将整个上游重新提交进平台仓库。"""
import json
import shutil
import subprocess
from pathlib import Path

REVISION = "e2401e54947db7eb5e542b6de26755d89886f783"
ROOT = Path(__file__).resolve().parents[1]


def main():
    repo = ROOT / "upstream" / "ragflow"
    if not repo.exists():
        subprocess.run(["git", "clone", "https://github.com/infiniflow/ragflow.git", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "checkout", REVISION], check=True)
    current = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    if current != REVISION:
        raise SystemExit("上游提交不匹配，停止以免覆盖用户代码")
    marker = repo / ".raglab-bridge.json"
    if marker.exists():
        print("桥接已准备；构建状态仍需单独验证")
        return
    if subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"], text=True).strip():
        raise SystemExit("上游有未提交更改，请先处理，脚本不会覆盖")
    source = ROOT / "patches" / "ragflow-parser-bridge" / "main.go"
    destination = repo / "cmd" / "raglab-parser"
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination / "main.go")
    build = repo / "build.sh"
    content = build.read_text(encoding="utf-8")
    target = "cmd/ragflow_server.go cmd/deepdoc_server_ee.go"
    if content.count(target) != 1:
        raise SystemExit("build.sh目标形状已变，需人工适配")
    content = content.replace(target, "./cmd/raglab-parser")
    content = content.replace('RAGFLOW_SERVER_BINARY="$PROJECT_ROOT/bin/ragflow_server"',
                              'RAGFLOW_SERVER_BINARY="$PROJECT_ROOT/bin/raglab_parser"')
    build.write_text(content, encoding="utf-8", newline="\n")
    marker.write_text(json.dumps({"revision": REVISION, "bridge_version": "1.0"}), encoding="utf-8")
    print("Go桥接已应用。请在具备Go/原生依赖的Linux环境按upstream/ragflow/AGENTS.md执行bash build.sh --go")


if __name__ == "__main__":
    main()
