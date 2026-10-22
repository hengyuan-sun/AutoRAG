"""在现有AGE容器创建隔离库和最小权限用户；不重建卷、不修改原业务。"""
import json
import secrets
import subprocess
from pathlib import Path


def main():
    if Path(".env").exists():
        print(".env已存在，保留现有配置")
        return
    container = "graphrag-postgres-age"
    info = json.loads(subprocess.check_output(["docker", "inspect", container]))[0]
    env = dict(x.split("=", 1) for x in info["Config"]["Env"] if "=" in x)
    suffix = secrets.token_hex(4)
    role, database, password = f"raglab_{suffix}", f"rag_lab_{suffix}", secrets.token_hex(24)
    sql = f"CREATE ROLE {role} LOGIN PASSWORD '{password}';\nCREATE DATABASE {database} OWNER {role};\n"
    command = ["docker", "exec", "-i", container, "psql", "-v", "ON_ERROR_STOP=1", "-U",
               env["POSTGRES_USER"], "-d", env.get("POSTGRES_DB", env["POSTGRES_USER"])]
    subprocess.run(command, input=sql.encode(), check=True, capture_output=True)
    subprocess.run(command[:-1]+[database], input=b"CREATE EXTENSION vector;", check=True, capture_output=True)
    token = secrets.token_urlsafe(32)
    Path(".env").write_text(f"RAGLAB_DATABASE_URL=postgresql+psycopg://{role}:{password}@127.0.0.1:5432/{database}\n"
                           f"RAGLAB_API_TOKEN={token}\nRAGLAB_STORAGE=storage\n"
                           "RAGLAB_OLLAMA_URL=http://127.0.0.1:11436\n"
                           "RAGLAB_EMBED_MODEL=qwen3-embedding:0.6b\nRAGLAB_VECTOR_DIM=1024\n", encoding="utf-8")
    print("隔离数据库和.env已创建；凭据仅保存在本地忽略文件")


if __name__ == "__main__":
    main()
