"""Lamp model discovery — Ollama, LM Studio, OpenAI-compatible endpoints (stdlib only)."""

import json
import re
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from workshop import load_config, probe_endpoint

# (id, label, base OpenAI-compatible /v1 URL, kind)
KNOWN_SOURCES = [
    ("ollama-local", "Ollama (this device)", "http://localhost:11434/v1", "ollama"),
    ("llamacpp-local", "llama.cpp server (this device)", "http://localhost:8080/v1", "llamacpp"),
    ("lmstudio-local", "LM Studio (this device)", "http://localhost:1234/v1", "openai"),
    ("ollama-pi", "Ollama (Pi / lamp.local)", "http://lamp.local:11434/v1", "ollama"),
    ("llamacpp-pi", "llama.cpp (Pi / lamp.local)", "http://lamp.local:8080/v1", "llamacpp"),
    ("litellm-local", "LiteLLM (this device)", "http://localhost:4000/v1", "openai"),
]

POPULAR_PATH = Path(__file__).resolve().parent / "data" / "ollama-popular.json"


def _fmt_size(n) -> str | None:
    if not n:
        return None
    try:
        n = int(n)
    except (TypeError, ValueError):
        return None
    for unit, div in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= div:
            return f"{n / div:.1f} {unit}"
    return f"{n} B"


def openai_base_to_host(endpoint: str) -> str | None:
    """http://localhost:8080/v1 -> http://localhost:8080"""
    if not endpoint:
        return None
    u = endpoint.rstrip("/")
    if u.endswith("/v1"):
        return u[:-3]
    return u


openai_base_to_ollama_host = openai_base_to_host  # alias


def infer_endpoint_kind(endpoint: str) -> str:
    """Guess backend type from URL (used for saved endpoints)."""
    ep = (endpoint or "").lower()
    if "11434" in ep or "ollama" in ep:
        return "ollama"
    if ":8080" in ep or "llama" in ep or "llamacpp" in ep:
        return "llamacpp"
    return "openai"


def fetch_openai_models(endpoint: str, api_key: str = None, timeout: float = 4) -> list:
    """Models from any OpenAI-compatible GET /v1/models."""
    try:
        req = urllib.request.Request(endpoint.rstrip("/") + "/models")
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        out = []
        for m in data.get("data", []):
            mid = m.get("id") or ""
            if not mid:
                continue
            out.append({
                "id": mid,
                "name": mid,
                "size": m.get("size"),
                "size_human": _fmt_size(m.get("size")),
                "owned_by": m.get("owned_by"),
                "installed": True,
                "parameter_size": None,
                "family": None,
            })
        return sorted(out, key=lambda x: x["name"].lower())
    except Exception:
        return []


def fetch_ollama_native(host: str, timeout: float = 4) -> list:
    """Installed models via Ollama GET /api/tags (richer than /v1/models)."""
    try:
        url = host.rstrip("/") + "/api/tags"
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.loads(r.read())
        out = []
        for m in data.get("models", []):
            name = m.get("name") or m.get("model") or ""
            if not name:
                continue
            details = m.get("details") or {}
            out.append({
                "id": name,
                "name": name,
                "size": m.get("size"),
                "size_human": _fmt_size(m.get("size")),
                "modified_at": m.get("modified_at"),
                "parameter_size": details.get("parameter_size"),
                "family": details.get("family"),
                "quantization": details.get("quantization_level"),
                "installed": True,
                "owned_by": "ollama",
            })
        return out
    except Exception:
        return []


def fetch_llamacpp_models(host: str, endpoint: str, api_key: str = None, timeout: float = 4) -> list:
    """
    Models from llama.cpp server (llama-server).
    Uses OpenAI GET /v1/models; falls back to /props when a single GGUF is loaded.
    """
    models = fetch_openai_models(endpoint, api_key, timeout)
    if models:
        return models
    if not host:
        return []
    try:
        url = host.rstrip("/") + "/props"
        req = urllib.request.Request(url)
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        path = (data.get("model_path") or data.get("model") or "").strip()
        if not path:
            return []
        name = Path(path).stem or "model"
        mod = data.get("model_alias") or data.get("model_name")
        if isinstance(mod, str) and mod.strip():
            name = mod.strip()
        return [{
            "id": name,
            "name": name,
            "size": None,
            "size_human": None,
            "installed": True,
            "owned_by": "llama.cpp",
            "parameter_size": None,
            "family": None,
            "path": path,
        }]
    except Exception:
        return []


def _llamacpp_reachable(host: str, api_key: str = None, timeout: float = 2) -> bool:
    if not host:
        return False
    base = host.rstrip("/")
    for path in ("/health", "/props", "/v1/models"):
        try:
            req = urllib.request.Request(base + path)
            if api_key:
                req.add_header("Authorization", f"Bearer {api_key}")
            with urllib.request.urlopen(req, timeout=timeout):
                return True
        except Exception:
            continue
    return False


def probe_source(source_id: str, label: str, endpoint: str, kind: str, api_key: str = None) -> dict:
    online = probe_endpoint(endpoint, api_key) is not None
    if not online and kind == "llamacpp":
        online = _llamacpp_reachable(openai_base_to_host(endpoint) or "", api_key)
    models = []
    if online:
        if kind == "ollama":
            host = openai_base_to_host(endpoint)
            models = fetch_ollama_native(host) if host else []
            if not models:
                models = fetch_openai_models(endpoint, api_key)
        elif kind == "llamacpp":
            host = openai_base_to_host(endpoint)
            models = fetch_llamacpp_models(host or "", endpoint, api_key)
        else:
            models = fetch_openai_models(endpoint, api_key)
    return {
        "id": source_id,
        "label": label,
        "endpoint": endpoint,
        "kind": kind,
        "online": online,
        "models": models,
        "model_count": len(models),
    }


def discover_sources(cfg: dict = None, extra_endpoints: list = None) -> list:
    """Probe all known sources + configured endpoint in parallel."""
    cfg = cfg or load_config()
    api_key = cfg.get("api_key")
    seen_urls = set()
    jobs = []

    for sid, label, url, kind in KNOWN_SOURCES:
        if url in seen_urls:
            continue
        seen_urls.add(url)
        jobs.append((sid, label, url, kind))

    ep = cfg.get("endpoint")
    if ep and ep not in seen_urls:
        seen_urls.add(ep)
        jobs.append(("configured", "Configured endpoint", ep, infer_endpoint_kind(ep)))

    for item in extra_endpoints or []:
        url = item.get("endpoint", "").strip()
        if url and url not in seen_urls:
            seen_urls.add(url)
            jobs.append((
                item.get("id", "custom"),
                item.get("label", "Custom"),
                url,
                item.get("kind", "openai"),
            ))

    results = [None] * len(jobs)
    lock = threading.Lock()

    def work(i, sid, label, url, kind):
        src = probe_source(sid, label, url, kind, api_key)
        with lock:
            results[i] = src

    threads = [
        threading.Thread(target=work, args=(i, *j), daemon=True)
        for i, j in enumerate(jobs)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=6)
    return [r for r in results if r]


def _load_popular() -> list:
    if POPULAR_PATH.is_file():
        try:
            return json.loads(POPULAR_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return [
        {"name": "qwen2.5:1.5b", "description": "Small, fast — good for 2GB Pi"},
        {"name": "qwen2.5:3b", "description": "Balanced for 4GB devices"},
        {"name": "qwen2.5:7b", "description": "Stronger — 8GB RAM recommended"},
        {"name": "llama3.2:3b", "description": "Meta Llama 3.2 small"},
        {"name": "llama3.1:8b", "description": "Meta Llama 3.1"},
        {"name": "phi3:mini", "description": "Microsoft Phi-3 mini"},
        {"name": "phi3", "description": "Microsoft Phi-3"},
        {"name": "gemma2:2b", "description": "Google Gemma 2 small"},
        {"name": "mistral:7b", "description": "Mistral 7B"},
        {"name": "codellama:7b", "description": "Code-focused 7B"},
    ]


def ollama_search_cli(query: str = "", limit: int = 20) -> list:
    """Use `ollama search` when available (Ollama 0.5+)."""
    try:
        cmd = ["ollama", "search", query or ""]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
        if r.returncode != 0:
            return []
        out = []
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if not line or line.startswith("NAME") or line.startswith("---"):
                continue
            parts = line.split()
            if parts:
                name = parts[0]
                out.append({
                    "name": name,
                    "description": " ".join(parts[1:]) if len(parts) > 1 else "",
                    "installed": False,
                })
            if len(out) >= limit:
                break
        return out
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


def catalog_search(query: str = "", limit: int = 30) -> dict:
    """
    Models available to download (not necessarily installed).
    Merges curated popular list + ollama search CLI.
    """
    q = (query or "").strip().lower()
    popular = _load_popular()
    if q:
        popular = [
            p for p in popular
            if q in p.get("name", "").lower() or q in p.get("description", "").lower()
        ]
    cli = ollama_search_cli(q, limit=limit)
    seen = {p["name"] for p in popular}
    for c in cli:
        if c["name"] not in seen:
            popular.append(c)
            seen.add(c["name"])
    return {
        "query": query,
        "models": popular[:limit],
        "source": "popular+ollama-search" if cli else "popular",
    }


def models_overview(cfg: dict = None) -> dict:
    cfg = cfg or load_config()
    sources = discover_sources(cfg)
    current_ep = cfg.get("endpoint") or ""
    current_model = cfg.get("model") or ""
    active_source = None
    for s in sources:
        if s["online"] and s["endpoint"] == current_ep:
            active_source = s["id"]
            break
    total = sum(s["model_count"] for s in sources)
    return {
        "current": {
            "endpoint": current_ep,
            "model": current_model,
            "source_id": active_source,
        },
        "sources": sources,
        "total_models": total,
        "recommendations": _recommendations(),
        "ollama_installed": any(
            s["kind"] == "ollama" and s["online"] for s in sources
        ),
        "llamacpp_installed": any(
            s["kind"] == "llamacpp" and s["online"] for s in sources
        ),
    }


def detect_models_flat(cfg: dict = None) -> list:
    """Flat {label, url, model} rows for /api/detect and chat model picker."""
    out = []
    for src in discover_sources(cfg):
        if not src.get("online"):
            continue
        for mod in src.get("models") or []:
            mid = mod.get("id") or mod.get("name") or ""
            if not mid:
                continue
            out.append({
                "label": src["label"],
                "url": src["endpoint"],
                "model": mid,
            })
    return out


def _recommendations() -> list:
    ram_mb = 2048
    try:
        if Path("/proc/meminfo").exists():
            for ln in Path("/proc/meminfo").read_text().splitlines():
                if ln.startswith("MemTotal:"):
                    ram_mb = int(ln.split()[1]) // 1024
                    break
    except (ValueError, OSError):
        pass
    if ram_mb >= 7000:
        return ["qwen2.5:7b", "llama3.1:8b", "mistral:7b"]
    if ram_mb >= 3000:
        return ["qwen2.5:3b", "phi3", "gemma2:2b"]
    return ["qwen2.5:1.5b", "phi3:mini"]


def switch_model(cfg: dict, endpoint: str, model: str) -> dict:
    cfg = dict(cfg)
    cfg["endpoint"] = endpoint.rstrip("/")
    if not cfg["endpoint"].endswith("/v1"):
        cfg["endpoint"] = cfg["endpoint"] + "/v1"
    cfg["model"] = model.strip()
    return cfg


def huggingface_to_ollama_ref(url: str) -> str | None:
    """
    Map Hugging Face page URLs to Ollama pull refs (hf.co/namespace/repo).
    See https://github.com/ollama/ollama/blob/main/docs/import.md
    """
    url = (url or "").strip()
    if not url:
        return None
    if re.match(r"^[\w.-]+/[\w.-]+", url) and "://" not in url:
        parts = url.split("/")
        if len(parts) >= 2:
            return f"hf.co/{parts[0]}/{parts[1]}"
        return None
    for prefix in (
        "https://huggingface.co/",
        "http://huggingface.co/",
        "https://hf.co/",
        "http://hf.co/",
    ):
        if url.startswith(prefix):
            path = url[len(prefix) :].split("?")[0].strip("/")
            skip = frozenset({"tree", "blob", "resolve", "main", "master", "files"})
            parts = [p for p in path.split("/") if p and p not in skip]
            if len(parts) >= 2:
                return f"hf.co/{parts[0]}/{parts[1]}"
    return None


def parse_import_url(url: str) -> dict:
    """
    Classify import URL for future handlers.
    Returns {type, model?, hint, supported}
    """
    url = (url or "").strip()
    if not url:
        return {"type": "invalid", "supported": False, "hint": "URL required"}

    if re.match(r"^[a-zA-Z0-9._/-]+:[a-zA-Z0-9._-]+$", url) and "://" not in url:
        return {
            "type": "ollama_name",
            "model": url,
            "supported": True,
            "hint": "Will run: ollama pull " + url,
        }

    hf_ref = huggingface_to_ollama_ref(url)
    if hf_ref or "huggingface.co" in url or "hf.co" in url:
        if hf_ref:
            return {
                "type": "huggingface",
                "url": url,
                "model": hf_ref,
                "supported": True,
                "hint": f"Will run: ollama pull {hf_ref}",
            }
        return {
            "type": "huggingface",
            "url": url,
            "supported": False,
            "hint": "Could not parse Hugging Face URL — use https://huggingface.co/org/model",
        }

    if url.startswith("ollama://") or "registry.ollama.ai" in url:
        name = url.split("/")[-1] if "/" in url else url.replace("ollama://", "")
        return {
            "type": "ollama_registry",
            "model": name,
            "supported": True,
            "hint": "Will run: ollama pull " + name,
        }

    return {
        "type": "unknown",
        "url": url,
        "supported": False,
        "hint": "Unsupported URL. Use an Ollama name (qwen2.5:3b) or Hugging Face (https://huggingface.co/org/model).",
    }


def import_from_url(url: str, name: str = None) -> dict:
    """Import model — Ollama names and Hugging Face URLs (via hf.co/… pull)."""
    parsed = parse_import_url(url if not name else name)
    model = parsed.get("model") or name or url
    if parsed.get("supported") and parsed["type"] in (
        "ollama_name",
        "ollama_registry",
        "huggingface",
    ):
        return {"ok": True, "action": "pull", "model": model, "parsed": parsed}
    return {"ok": False, "error": parsed.get("hint", "Not supported"), "parsed": parsed}
