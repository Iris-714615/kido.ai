import importlib.util as u
mods = [
    "gradio",
    "llama_index",
    "llama_index.llms.dashscope",
    "llama_index.embeddings.dashscope",
    "langsmith",
    "dotenv",
]
for m in mods:
    print(m, "OK" if u.find_spec(m) else "MISSING")
