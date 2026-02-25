import os
import importlib
from typing import Dict, List, Any, Optional
from tools.base_tool import BaseTool, ToolOutput
from utils.logger import logger_instance


class ToolManager:
    def __init__(self):
        self.tools: Dict[str, BaseTool] = {}
        self.logger = logger_instance.get_logger("tool_manager")
        self._load_available_tools()

    def _load_available_tools(self):
        tools_dir = os.path.join(os.path.dirname(__file__), "available")
        if not os.path.exists(tools_dir):
            self.logger.warning("Available tools directory not found")
            return

        for filename in os.listdir(tools_dir):
            if filename.endswith(".py") and filename != "__init__.py":
                module_name = filename[:-3]
                try:
                    module = importlib.import_module(
                        f"tools.available.{module_name}"
                    )

                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if (isinstance(attr, type) and
                            issubclass(attr, BaseTool) and
                            attr != BaseTool):
                            tool_instance = attr()
                            self.register_tool(tool_instance)

                except Exception as e:
                    self.logger.error(
                        f"Failed to load tool from {filename}: {e}"
                    )

    def register_tool(self, tool: BaseTool):
        self.tools[tool.name] = tool
        self.logger.info(f"Registered tool: {tool.name}")

    def get_tool(self, tool_name: str) -> Optional[BaseTool]:
        return self.tools.get(tool_name)

    def execute_tool(self, tool_name: str,
                     input_data: Dict[str, Any]) -> ToolOutput:
        tool = self.get_tool(tool_name)
        if not tool:
            error_msg = f"Tool '{tool_name}' not found"
            self.logger.error(error_msg)
            return ToolOutput(success=False, result=None, error=error_msg)

        result = tool.execute(input_data)

        return result

    def get_tools_description(self) -> str:
        descriptions = []
        for tool in self.tools.values():
            descriptions.append(f"- {tool.name}: {tool.description}")
        return "\n".join(descriptions)