import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    def __init__(self):
        # LLM Configuration (OpenAI via litellm - switchable to gemini/others)
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.default_model = os.getenv("DEFAULT_MODEL", "gpt-4o")
        self.max_iterations = int(os.getenv("MAX_ITERATIONS", "5"))
        self.temperature = float(os.getenv("TEMPERATURE", "0.7"))
        self.max_tokens = int(os.getenv("MAX_TOKENS", "4000"))
        self.memory_file = os.getenv("MEMORY_FILE", "agent_memory.json")
        self.log_level = os.getenv("LOG_LEVEL", "INFO")

        # RAG / Vector Store Configuration
        self.chroma_db_path = os.getenv("CHROMA_DB_PATH", "./chroma_db")
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
        self.chunk_size = int(os.getenv("CHUNK_SIZE", "500"))
        self.chunk_overlap = int(os.getenv("CHUNK_OVERLAP", "50"))
        self.rag_top_k = int(os.getenv("RAG_TOP_K", "5"))

        # Knowledge Base
        self.knowledge_base_path = os.getenv(
            "KNOWLEDGE_BASE_PATH", "./knowledge_data"
        )

        # Document Upload
        self.upload_dir = os.getenv("UPLOAD_DIR", "./uploads")
        self.max_upload_size_mb = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))
        self.allowed_extensions = {"pdf", "docx", "txt"}


config = Config()