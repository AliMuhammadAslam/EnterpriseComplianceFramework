import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    def __init__(self):
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.default_model = os.getenv("DEFAULT_MODEL", "gpt-4o")
        self.max_iterations = int(os.getenv("MAX_ITERATIONS", "5"))
        self.temperature = float(os.getenv("TEMPERATURE", "0.7"))
        self.max_tokens = int(os.getenv("MAX_TOKENS", "2000"))
        self.memory_file = os.getenv("MEMORY_FILE", "agent_memory.json")
        self.log_level = os.getenv("LOG_LEVEL", "INFO")


config = Config()