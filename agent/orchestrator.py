import os
from pydantic import BaseModel
from dotenv import load_dotenv
from typing import Dict, Any, Optional
from utils.logger import logger_instance

from agent.perception import Perception
from agent.memory import Memory
from agent.planner import Planner
from agent.executor import Executor
from knowledge.vector_store import VectorStore
from knowledge.rag_pipeline import RAGPipeline
from knowledge.knowledge_base import KnowledgeBase
from evaluation.engine import EvaluationEngine
from document_upload.manager import UploadManager

load_dotenv()


class OrchestrationResult(BaseModel):
    success: bool
    result: str
    strategy_used: str
    steps_executed: int = 0
    error: Optional[str] = None


class Orchestrator:
    """Central coordinator for the compliance agent pipeline.

    On each user query, the pipeline runs in order:
        1. Perception  — classify the user's intent
        2. RAG         — retrieve relevant regulatory and company doc context
        3. Planner     — generate a structured step plan (LLM + RAG context)
        4. Executor    — execute the plan step by step (LLM + RAG context)
        5. Memory      — store the interaction for the session
    """

    def __init__(self, model_name: str = "gpt-4o", agent_role: str = ""):
        self.model_name = model_name
        self.agent_role = agent_role
        self.logger = logger_instance.get_logger("orchestrator")

        self.perception = Perception()
        self.memory = Memory()
        self.planner = Planner(model_name)
        self.executor = Executor(model_name)

        self.vector_store = VectorStore()
        self.rag_pipeline = RAGPipeline(self.vector_store)
        self.knowledge_base = KnowledgeBase(self.vector_store)
        self.evaluation_engine = EvaluationEngine(self.rag_pipeline)
        self.upload_manager = UploadManager(self.vector_store)

        self._initialize_knowledge_base()
        self.logger.info("Orchestrator initialised")

    def _initialize_knowledge_base(self):
        """Ingest regulatory knowledge base on first startup."""
        try:
            if not self.knowledge_base.is_populated():
                self.logger.info("Ingesting regulatory knowledge base...")
                self.knowledge_base.ingest()
                self.logger.info("Knowledge base ingestion complete")
            else:
                self.logger.info("Knowledge base already populated")
        except Exception as e:
            self.logger.error(f"Error initialising knowledge base: {e}")

    def run(
        self,
        user_input: str,
        verbose: bool = False,
        user_id: str = "default",
    ) -> OrchestrationResult:
        """Process a user query through the full agent pipeline."""
        try:
            if verbose:
                print(f"[ORCHESTRATOR] Input: {user_input[:100]}...")

            self.logger.info(f"Processing: {user_input[:100]}...")

            # Step 1: Perception
            perception_output = self.perception.process_input(user_input)
            if verbose:
                print(f"[PERCEPTION] Intent: {perception_output.intent}")

            # Step 2: RAG retrieval
            rag_context = self.rag_pipeline.retrieve_context(user_input, user_id=user_id)
            if verbose:
                print(f"[RAG] Retrieved {len(rag_context)} chars of context")

            # Steps 3 + 4: Plan and execute
            if verbose:
                print("[PLANNER] Creating plan...")

            plan = self.planner.create_plan(perception_output, rag_context=rag_context)

            if verbose:
                print(f"[PLANNER] {len(plan.steps)} steps:")
                for step in plan.steps:
                    print(f"           {step.step_number}. {step.description}")
                print("[EXECUTOR] Executing plan...")

            execution_result = self.executor.execute_plan(plan, verbose, rag_context=rag_context)

            # Step 5: Memory
            self.memory.add_interaction(user_input, execution_result.result)

            if verbose:
                print("[ORCHESTRATOR] Done")

            self.logger.info("Orchestration complete")
            return OrchestrationResult(
                success=execution_result.success,
                result=execution_result.result,
                strategy_used="plan_and_execute",
                steps_executed=len(execution_result.step_results),
                error=execution_result.error,
            )

        except Exception as e:
            self.logger.error(f"Orchestration failed: {e}")
            return OrchestrationResult(
                success=False,
                result="I encountered an error while processing your request.",
                strategy_used="error",
                error=str(e),
            )

    def evaluate_compliance(
        self,
        user_id: str,
        standards: list = None,
        industry: str = "",
        country: str = "",
    ) -> str:
        """Run a compliance evaluation for a user's uploaded documents."""
        return self.evaluation_engine.evaluate_compliance(
            user_id=user_id,
            standards=standards,
            industry=industry,
            country=country,
        )

    def get_system_status(self) -> Dict[str, Any]:
        """Return current status of all system components."""
        return {
            "components": {
                "perception": "active",
                "memory": {
                    "short_term_entries": len(self.memory.short_term_memory),
                    "long_term_entries": len(self.memory.long_term_memory),
                },
                "planner": "active",
                "executor": "active",
                "rag_pipeline": self.rag_pipeline.get_status(),
                "knowledge_base": self.knowledge_base.get_status(),
                "evaluation_engine": "active",
            },
            "configuration": {
                "model": self.model_name,
                "role": self.agent_role,
                "strategy": "plan_and_execute",
            },
        }

    def reset_session(self):
        """End the current session and start a fresh one."""
        self.memory.end_current_session()
        self.memory.start_new_session()
        self.logger.info("Session reset")
