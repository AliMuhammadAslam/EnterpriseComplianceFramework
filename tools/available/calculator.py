import ast
import operator
from typing import Dict, Any
from pydantic import BaseModel
from tools.base_tool import BaseTool, ToolInput

class CalculatorInput(ToolInput):
    expression: str

class CalculatorTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="calculator",
            description="Performs mathematical calculations on expressions"
        )
        
        self.operators = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.Pow: operator.pow,
            ast.BitXor: operator.xor,
            ast.USub: operator.neg,
            ast.Mod: operator.mod,
        }
    
    def get_input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Mathematical expression to calculate (e.g., '2 + 3 * 4', '15 ** 2', '100 / 4')"
                }
            },
            "required": ["expression"]
        }
    
    def _validate_input(self, input_data: Dict[str, Any]) -> CalculatorInput:
        return CalculatorInput(**input_data)
    
    def _execute(self, input_data: CalculatorInput) -> float:
        try:
            tree = ast.parse(input_data.expression, mode='eval')
            result = self._eval_expr(tree.body)
            return float(result)
        except Exception as e:
            raise ValueError(f"Invalid mathematical expression: {str(e)}")
    
    def _eval_expr(self, node):
        if isinstance(node, ast.Num):
            return node.n
        elif isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.BinOp):
            return self.operators[type(node.op)](
                self._eval_expr(node.left),
                self._eval_expr(node.right)
            )
        elif isinstance(node, ast.UnaryOp):
            return self.operators[type(node.op)](self._eval_expr(node.operand))
        else:
            raise TypeError(f"Unsupported operation: {type(node)}")