# backend/services/agents/registry.py
AGENT_REGISTRY = {
    "general-chat": {
        "label": "通用大模型",
        "enabled": True,
        "model_env": "OLLAMA_MODEL_GENERAL_CHAT",
        "fallback_model": "qwen3:32b",
    },
    "platform-guide": {
        "label": "平台导览智能体",
        "enabled": True,
        "model_env": "OLLAMA_MODEL_PLATFORM_GUIDE",
        "fallback_model": "qwen2.5:7b",
    },
    
    # 以后可以继续加：
    # "literature": {
    #     "label": "文献助手",
    #     "enabled": True,
    #     "model_env": "OLLAMA_MODEL_LITERATURE",
    #     "fallback_model": "qwen2.5:14b",
    # },
    # "server-monitor": {
    #     "label": "服务器助手",
    #     "enabled": True,
    #     "model_env": "OLLAMA_MODEL_SERVER_MONITOR",
    #     "fallback_model": "qwen2.5:7b",
    # },
}

