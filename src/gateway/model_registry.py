class ModelRegistry:
    def __init__(self):
        self.MODELS: dict[str, dict] = {}

    def get_model(self, agent_name: str) -> dict | None:
        return self.MODELS.get(agent_name)

    def register(self, agent_name: str, model_config: dict):
        """注册模型。model_config 需包含 model 字段，可选 provider/base_url/api_key。"""
        self.MODELS[agent_name] = model_config
        print(f"[registry] registered: {agent_name} -> {model_config.get('model', 'unknown')}")

    def register_deepseek(self, agent_name: str, model: str = "deepseek-chat"):
        """快捷注册 DeepSeek 模型。"""
        self.MODELS[agent_name] = {"provider": "deepseek", "model": model}
        print(f"[registry] registered deepseek: {agent_name} -> {model}")

    def switch_to_finetuned(self, agent_name: str, model: str, base_url: str, api_key: str):
        self.MODELS[agent_name] = {
            "provider": "openai",
            "model": model,
            "base_url": base_url,
            "api_key": api_key,
        }
        print(f"[registry] switched {agent_name} to finetuned: {model}")


model_registry = ModelRegistry()
