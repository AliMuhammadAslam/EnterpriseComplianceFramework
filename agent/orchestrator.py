import os
from pydantic import BaseModel
from dotenv import load_dotenv
from typing import Dict, Any, Optional
from utils.logger import logger_instance
from utils import run_config

from agent.perception import Perception
from agent.memory import Memory
from agent.planner import Planner
from agent.executor import Executor
from knowledge.vector_store import VectorStore
from knowledge.rag_pipeline import RAGPipeline
from knowledge.knowledge_base import KnowledgeBase
from evaluation.engine import EvaluationEngine
from document_upload.manager import UploadManager
from audit.evidence_trace import EvidenceTraceStore, ToolCall

load_dotenv()


class OrchestrationResult(BaseModel):
    success: bool
    result: str
    strategy_used: str
    steps_executed: int = 0
    error: Optional[str] = None
    trace_id: str = ""


class Orchestrator:
    """Coordinates the full agent pipeline: perception → RAG → plan → execute → memory."""

    def __init__(self, model_name: str = "", agent_role: str = ""):
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
        self.trace_store = EvidenceTraceStore()

        self._initialize_knowledge_base()
        self.logger.info("Orchestrator initialised")

    def _initialize_knowledge_base(self):
        """Ingest the knowledge base on startup; re-ingest if files have changed."""
        try:
            knowledge_path = os.getenv("KNOWLEDGE_BASE_PATH", "./knowledge_data")
            current_hash = self._hash_knowledge_files(knowledge_path)
            hash_file = os.path.join(knowledge_path, ".kb_hash")

            stored_hash = ""
            if os.path.exists(hash_file):
                with open(hash_file, "r", encoding="utf-8") as f:
                    stored_hash = f.read().strip()

            needs_ingest = (
                not self.knowledge_base.is_populated()
                or current_hash != stored_hash
            )

            if needs_ingest:
                self.logger.info("Ingesting regulatory knowledge base (new or updated files)...")
                self.knowledge_base.ingest(force=True)
                with open(hash_file, "w", encoding="utf-8") as f:
                    f.write(current_hash)
                self.logger.info("Knowledge base ingestion complete")
            else:
                self.logger.info("Knowledge base up to date, skipping ingestion")
        except Exception as e:
            self.logger.error(f"Error initialising knowledge base: {e}")

    def _hash_knowledge_files(self, knowledge_path: str) -> str:
        """SHA-256 hash of all knowledge files, used to detect content changes.

        Same hash the run manifest records as the corpus identifier.
        """
        return run_config.hash_corpus(knowledge_path)

    def run(
        self,
        user_input: str,
        verbose: bool = False,
        user_id: str = "default",
    ) -> OrchestrationResult:
        """Process a user query through the full pipeline."""
        try:
            if verbose:
                print(f"[ORCHESTRATOR] Input: {user_input[:100]}...")

            self.logger.info(f"Processing: {user_input[:100]}...")

            # perception
            perception_output = self.perception.process_input(user_input)
            if verbose:
                print(f"[PERCEPTION] Intent: {perception_output.intent}")

            # context retrieval
            rag_context, retrieved = self.rag_pipeline.retrieve_context_with_results(
                user_input, user_id=user_id
            )
            if verbose:
                print(f"[RAG] Retrieved {len(rag_context)} chars of context")

            # prior conversation (scoped to this user) for follow-up questions
            conversation_context = self._format_conversation_history(
                self.memory.get_conversation_history(user_id=user_id, limit=3)
            )
            if verbose and conversation_context:
                print("[MEMORY] Injecting prior conversation turns for context")

            # plan and execute
            if verbose:
                print("[PLANNER] Creating plan...")

            plan = self.planner.create_plan(
                perception_output,
                rag_context=rag_context,
                conversation_context=conversation_context,
            )

            if verbose:
                print(f"[PLANNER] {len(plan.steps)} steps:")
                for step in plan.steps:
                    print(f"           {step.step_number}. {step.description}")
                print("[EXECUTOR] Executing plan...")

            execution_result = self.executor.execute_plan(
                plan,
                verbose,
                rag_context=rag_context,
                conversation_context=conversation_context,
            )

            # store interaction (scoped to this user)
            self.memory.add_interaction(
                user_input, execution_result.result, user_id=user_id
            )

            trace_id = self._record_trace(
                user_input=user_input,
                user_id=user_id,
                perception_output=perception_output,
                retrieved=retrieved,
                plan=plan,
                execution_result=execution_result,
            )

            if verbose:
                print("[ORCHESTRATOR] Done")

            self.logger.info("Orchestration complete")
            return OrchestrationResult(
                success=execution_result.success,
                result=execution_result.result,
                strategy_used="plan_and_execute",
                steps_executed=len(execution_result.step_results),
                error=execution_result.error,
                trace_id=trace_id,
            )

        except Exception as e:
            self.logger.error(f"Orchestration failed: {e}")
            return OrchestrationResult(
                success=False,
                result="I encountered an error while processing your request.",
                strategy_used="error",
                error=str(e),
            )

    def _record_trace(
        self,
        user_input: str,
        user_id: str,
        perception_output,
        retrieved: list,
        plan,
        execution_result,
    ) -> str:
        """Write an evidence trace and return its id.

        A trace failure must never fail the user's request.
        """
        try:
            tool_calls = [
                ToolCall(
                    name="rag_retrieval",
                    arguments={"top_k": self.rag_pipeline.top_k, "user_id": user_id},
                    outcome=f"{len(retrieved)} chunks retrieved",
                    succeeded=bool(retrieved),
                ),
                ToolCall(
                    name="planner",
                    arguments={"intent": getattr(perception_output, "intent", "")},
                    outcome=f"{len(plan.steps)} step plan",
                    succeeded=True,
                ),
                ToolCall(
                    name="executor",
                    arguments={"steps": len(plan.steps)},
                    outcome=f"{len(execution_result.step_results)} steps executed",
                    succeeded=execution_result.success,
                ),
            ]

            trace = self.trace_store.build(
                request=user_input,
                user_id=user_id,
                intent=getattr(perception_output, "intent", ""),
                model_configuration=run_config.model_configuration(),
                retrieved=retrieved,
                plan=plan,
                tool_calls=tool_calls,
                final_answer=execution_result.result,
            )
            self.trace_store.save(trace)
            return trace.trace_id
        except Exception as e:
            self.logger.error(f"Failed to record evidence trace: {e}")
            return ""

    def _format_conversation_history(self, history: list) -> str:
        """Format recent user/agent turns into a compact context block."""
        if not history:
            return ""
        lines = []
        for turn in history:
            query = (turn.get("query") or "").strip()
            response = (turn.get("response") or "").strip()
            if not query:
                continue
            # keep responses bounded so history doesn't dominate the prompt
            if len(response) > 600:
                response = response[:600] + "..."
            lines.append(f"User: {query}\nAssistant: {response}")
        return "\n\n".join(lines)

    def evaluate_compliance(
        self,
        user_id: str,
        standards: list = None,
        industry: str = "",
        country: str = "",
        doc_ids: list = None,
        verbose: bool = False,
    ) -> str:
        """Delegate to the evaluation engine for a user's compliance report."""
        return self.evaluation_engine.evaluate_compliance(
            user_id=user_id,
            standards=standards,
            industry=industry,
            country=country,
            doc_ids=doc_ids,
            verbose=verbose,
        )

    def get_system_status(self) -> Dict[str, Any]:
        """Return status for all pipeline components."""
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
                "model": self.model_name or run_config.model_name(),
                "role": self.agent_role,
                "strategy": "plan_and_execute",
            },
        }

    def reset_session(self, user_id: str = "default"):
        """Clear a user's conversation memory and start a fresh session."""
        self.memory.end_current_session()
        self.memory.start_new_session()
        self.memory.clear_user_conversation(user_id)
        self.logger.info(f"Session reset for user: {user_id}")
