import argparse
import sys
import os
from dotenv import load_dotenv
from agent.orchestrator import Orchestrator
from utils.logger import logger_instance

load_dotenv()


class AgentCLI:
    def __init__(self):
        self.orchestrator = Orchestrator()
        self.logger = logger_instance.get_logger("main")

    def interactive_mode(self):
        print("AI Agent Framework - Interactive Mode")
        print("Type 'quit', 'exit', or 'terminate' to end the session")
        print("Type 'status' to see system status")
        print("Type 'reset' to clear conversation history")
        print("Type 'verbose' to toggle detailed execution logs")
        print("-" * 50)
        
        verbose_mode = False
        
        while True:
            try:
                user_input = input("\nUser: ").strip()
                
                if not user_input:
                    continue
                    
                if user_input.lower() in ['quit', 'exit', 'terminate']:
                    self.orchestrator.memory.end_current_session()
                    print("Session terminated.")
                    break
                    
                if user_input.lower() == 'status':
                    self._show_status()
                    continue
                    
                if user_input.lower() == 'reset':
                    self.orchestrator.reset_session(user_id="cli_user")
                    print("Session reset. Conversation history cleared.")
                    continue
                
                if user_input.lower() == 'verbose':
                    verbose_mode = not verbose_mode
                    print(f"Verbose mode: {'ON' if verbose_mode else 'OFF'}")
                    continue
                
                print("Agent: Processing request...")
                result = self.orchestrator.run(user_input, verbose=verbose_mode, user_id="cli_user")
                
                if result.success:
                    print(f"Agent: {result.result}")
                    if result.strategy_used == "plan_and_execute":
                        print(f"   (Used {result.strategy_used} strategy with {result.steps_executed} steps)")
                    else:
                        print(f"   (Used {result.strategy_used} strategy)")
                else:
                    print(f"Error: {result.result}")
                    if result.error:
                        print(f"   Details: {result.error}")
                        
            except KeyboardInterrupt:
                self.orchestrator.memory.end_current_session()
                print("\nSession terminated.")
                break
            except Exception as e:
                print(f"Unexpected error: {str(e)}")
                self.logger.error(f"CLI error: {e}")
                
    def batch_mode(self, query: str, verbose: bool = False) -> str:
        try:
            result = self.orchestrator.run(query, verbose=verbose)
            return result.result
        except Exception as e:
            error_msg = f"Error processing query: {str(e)}"
            self.logger.error(error_msg)
            return error_msg
    
    def _show_status(self):
        status = self.orchestrator.get_system_status()
        
        print("\nSystem Status:")
        print(f"   Model: {status['configuration']['model']}")
        print(f"   Memory Entries: "
              f"{status['components']['memory']['short_term_entries']} "
              f"short-term, "
              f"{status['components']['memory']['long_term_entries']} "
              f"long-term")
        print(f"   Components: All active")

def main():
    parser = argparse.ArgumentParser(description="AI Agent Framework")
    parser.add_argument(
        "--mode", 
        choices=["interactive", "batch"], 
        default="interactive",
        help="Run mode: interactive for conversation, batch for single query"
    )
    parser.add_argument(
        "--query", 
        type=str,
        help="Query to process in batch mode"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-4o",
        help="LLM model to use (default: gpt-4o)"
    )
    parser.add_argument(
        "--role",
        type=str,
        default="You are a helpful AI assistant.",
        help="Agent role/persona"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    if args.mode == "batch" and not args.query:
        print("Error: --query is required for batch mode")
        sys.exit(1)
    
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable is not set")
        print("Please set your OpenAI API key in a .env file or environment variable")
        sys.exit(1)
    
    try:
        cli = AgentCLI()
        if (args.model != "gpt-4o" or
                args.role != "You are a helpful AI assistant."):
            cli.orchestrator = Orchestrator(args.model, args.role)
        
        if args.verbose:
            print(f"Configuration:")
            print(f"   Mode: {args.mode}")
            print(f"   Model: {args.model}")
            print(f"   Role: {args.role}")
            print()
        
        if args.mode == "interactive":
            cli.interactive_mode()
        else:
            result = cli.batch_mode(args.query, verbose=args.verbose)
            print(result)
            
    except Exception as e:
        print(f"Failed to start agent: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()