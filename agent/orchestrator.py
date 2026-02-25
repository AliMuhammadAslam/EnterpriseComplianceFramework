from pydantic import BaseModel
from dotenv import load_dotenv
import logging
from typing import Dict, Any, Optional
from utils.logger import logger_instance

from agent.perception import Perception
from agent.memory import Memory
from agent.planner import Planner
from agent.executor import Executor
from tools.tool_manager import ToolManager
from knowledge.vector_store import VectorStore
from knowledge.rag_pipeline import RAGPipeline
from knowledge.knowledge_base import KnowledgeBase
from evaluation.engine import EvaluationEngine
from document_upload.manager import UploadManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()


class OrchestrationResult(BaseModel):
    success: bool
    result: str
    strategy_used: str
    steps_executed: int = 0
    error: Optional[str] = None


class Orchestrator:
    def __init__(self, model_name="gpt-4o", agent_role=""):
        self.model_name = ""
        self.role = agent_role + "\n"
        if model_name.lower()[0:3] == "gpt":
            self.model_name = "openai/" + model_name

        self.logger = logger_instance.get_logger("orchestrator")

        # Core agent components (preserved from original)
        self.perception = Perception()
        self.memory = Memory()
        self.tool_manager = ToolManager()
        self.planner = Planner(model_name, agent_role)
        self.executor = Executor(model_name, agent_role)

        # RAG + Knowledge Base + Evaluation (new components)
        self.vector_store = VectorStore()
        self.rag_pipeline = RAGPipeline(self.vector_store)
        self.knowledge_base = KnowledgeBase(self.vector_store)
        self.evaluation_engine = EvaluationEngine(self.rag_pipeline)
        self.upload_manager = UploadManager(self.vector_store)

        # Auto-ingest knowledge base on startup
        self._initialize_knowledge_base()

        self.logger.info("Orchestrator initialized with all components")

    def _initialize_knowledge_base(self):
        """Ingest regulatory knowledge base if not already populated."""
        try:
            if not self.knowledge_base.is_populated():
                self.logger.info("Ingesting regulatory knowledge base...")
                self.knowledge_base.ingest()
                self.logger.info("Knowledge base ingestion complete")
            else:
                self.logger.info("Knowledge base already populated")
        except Exception as e:
            self.logger.error(f"Error initializing knowledge base: {e}")

    def run(
        self,
        user_input: str,
        verbose: bool = False,
        user_id: str = "default",
    ) -> OrchestrationResult:
        """Process a user query using PLANNING + EXECUTION pattern with RAG.
        
        Every query follows this flow:
        1. Perception: classify intent
        2. RAG: retrieve relevant context from knowledge base + company docs
        3. Planning: create a structured plan with RAG context
        4. Execution: execute the plan step by step
        5. Memory: store the interaction
        """
        try:
            if verbose:
                print("[ORCHESTRATOR] Starting processing...")
                print(f"[ORCHESTRATOR] Input: {user_input[:100]}...")

            self.logger.info(f"Processing user input: {user_input[:100]}...")

            # Step 1: Perception
            if verbose:
                print("[PERCEPTION] Processing input...")

            perception_output = self.perception.process_input(user_input)

            if verbose:
                print(
                    f"[PERCEPTION] Intent detected: "
                    f"{perception_output.intent}"
                )

            self.logger.info(
                f"Perception completed - Intent: {perception_output.intent}"
            )

            # Step 2: RAG Retrieval (always triggered before LLM)
            if verbose:
                print("[RAG] Retrieving relevant context...")

            rag_context = self.rag_pipeline.retrieve_context(
                user_input, user_id=user_id
            )

            if verbose:
                print(f"[RAG] Retrieved context ({len(rag_context)} chars)")

            self.logger.info(f"RAG context retrieved: {len(rag_context)} chars")

            # Step 3 + 4: Planning + Execution (always used)
            if verbose:
                print(
                    "[EXECUTION] Using Plan-and-Execute strategy "
                    "with RAG context..."
                )

            result = self._execute_plan_and_execute(
                perception_output, rag_context, verbose
            )

            # Step 5: Memory
            if verbose:
                print("[MEMORY] Storing interaction...")

            self.memory.add_interaction(user_input, result.result)

            if verbose:
                print("[ORCHESTRATOR] Processing completed successfully")

            self.logger.info("Orchestration completed using plan_and_execute")
            return result

        except Exception as e:
            error_msg = f"Orchestration failed: {str(e)}"
            if verbose:
                print(f"[ORCHESTRATOR] Error: {error_msg}")
            self.logger.error(error_msg)
            return OrchestrationResult(
                success=False,
                result="I encountered an error while processing your request.",
                strategy_used="error",
                error=error_msg,
            )

    def _execute_plan_and_execute(
        self,
        perception_output,
        rag_context: str,
        verbose: bool = False,
    ) -> OrchestrationResult:
        """Execute the Planning + Execution strategy with RAG context."""
        try:
            if verbose:
                print("[PLANNER] Creating plan with RAG context...")

            available_tools = list(self.tool_manager.tools.keys())
            plan = self.planner.create_plan(
                perception_output, available_tools, rag_context=rag_context
            )

            if verbose:
                print(f"[PLANNER] Created plan with {len(plan.steps)} steps:")
                for i, step in enumerate(plan.steps, 1):
                    print(f"[PLANNER]   Step {i}: {step.description}")
                    if step.tool_required:
                        print(f"[PLANNER]     Tool: {step.tool_required}")

            if verbose:
                print("[EXECUTOR] Executing plan...")

            execution_result = self.executor.execute_plan(
                plan, self.tool_manager, verbose, rag_context=rag_context
            )

            if verbose:
                print(
                    f"[EXECUTOR] Plan execution completed with "
                    f"{len(execution_result.step_results)} steps"
                )

            return OrchestrationResult(
                success=execution_result.success,
                result=execution_result.result,
                strategy_used="plan_and_execute",
                steps_executed=len(execution_result.step_results),
                error=execution_result.error,
            )

        except Exception as e:
            if verbose:
                print(f"[PLAN_AND_EXECUTE] Error: {str(e)}")
            return OrchestrationResult(
                success=False,
                result="Failed to execute plan and execute strategy.",
                strategy_used="plan_and_execute",
                error=str(e),
            )

    def evaluate_compliance(
        self,
        user_id: str,
        standards: list = None,
        industry: str = "",
        country: str = "",
    ) -> str:
        """Run a compliance evaluation for a user's documents."""
        return self.evaluation_engine.evaluate_compliance(
            user_id=user_id,
            standards=standards,
            industry=industry,
            country=country,
        )

    def get_system_status(self) -> Dict[str, Any]:
        return {
            "components": {
                "perception": "active",
                "memory": {
                    "short_term_entries": len(self.memory.short_term_memory),
                    "long_term_entries": len(self.memory.long_term_memory),
                },
                "planner": "active",
                "executor": "active",
                "tool_manager": {
                    "available_tools": len(self.tool_manager.tools),
                    "tools": list(self.tool_manager.tools.keys()),
                },
                "rag_pipeline": self.rag_pipeline.get_status(),
                "knowledge_base": self.knowledge_base.get_status(),
                "evaluation_engine": "active",
            },
            "configuration": {
                "model": self.model_name,
                "role": self.role.strip(),
                "strategy": "plan_and_execute (always)",
            },
        }

    def reset_session(self):
        self.memory.end_current_session()
        self.memory.start_new_session()
        self.logger.info("Session reset completed")
