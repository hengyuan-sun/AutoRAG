"""Ollama模型绑定：标签只是入口，digest才是索引身份。"""
import httpx


class Ollama:
    def __init__(self, url, model, dimension):
        self.url, self.model, self.dimension = url.rstrip("/"), model, dimension

    def binding(self, model_name=None):
        model_name = model_name or self.model
        with httpx.Client(timeout=15, trust_env=False) as c:
            response = c.get(self.url + "/api/tags")
            response.raise_for_status()
        found = next((m for m in response.json()["models"] if m["name"] == model_name), None)
        if not found:
            raise ValueError("Ollama未安装指定Embedding模型")
        return {"model": model_name, "digest": found["digest"], "dimension": self.dimension,
                "query_prefix": "Instruct: Retrieve relevant document passages for the query.\nQuery: "}

    def embed(self, texts, binding):
        if self.binding(binding["model"])["digest"] != binding["digest"]:
            raise ValueError("Embedding模型digest已改变，拒绝混用索引")
        with httpx.Client(timeout=180, trust_env=False) as c:
            r = c.post(self.url + "/api/embed", json={"model": binding["model"], "input": texts,
                                                        "truncate": False, "keep_alive": "10m"})
            r.raise_for_status()
            vectors = r.json()["embeddings"]
        if len(vectors) != len(texts) or any(len(v) != binding["dimension"] for v in vectors):
            raise ValueError("Embedding响应数量或维度异常")
        return vectors
