import requests
import os
from typing import Dict, Any, List
from pydantic import BaseModel
from tools.base_tool import BaseTool, ToolInput

class WebSearchInput(ToolInput):
    query: str
    max_results: int = 3

class WebSearchTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="web_search",
            description="Searches the web for information using Serper API"
        )
        self.api_key = os.getenv('SERPER_API_KEY')
        if not self.api_key:
            raise ValueError("SERPER_API_KEY environment variable is required")
    
    def get_input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query string"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of search results to return",
                    "default": 3
                }
            },
            "required": ["query"]
        }
    
    def _validate_input(self, input_data: Dict[str, Any]) -> WebSearchInput:
        return WebSearchInput(**input_data)
    
    def _execute(self, input_data: WebSearchInput) -> List[Dict[str, str]]:
        try:
            url = "https://google.serper.dev/search"
            
            headers = {
                'X-API-KEY': self.api_key,
                'Content-Type': 'application/json'
            }
            
            payload = {
                'q': input_data.query,
                'num': input_data.max_results
            }
            
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            results = []
            
            # Extract organic search results
            for result in data.get('organic', [])[:input_data.max_results]:
                results.append({
                    "title": result.get('title', ''),
                    "snippet": result.get('snippet', ''),
                    "url": result.get('link', '')
                })
            
            # If no organic results, try knowledge graph or answer box
            if not results:
                if data.get('answerBox'):
                    answer_box = data.get('answerBox')
                    results.append({
                        "title": answer_box.get('title', 'Answer'),
                        "snippet": answer_box.get('answer', answer_box.get('snippet', '')),
                        "url": answer_box.get('link', '')
                    })
                elif data.get('knowledgeGraph'):
                    kg = data.get('knowledgeGraph')
                    results.append({
                        "title": kg.get('title', 'Knowledge Graph'),
                        "snippet": kg.get('description', ''),
                        "url": kg.get('website', '')
                    })
            
            if not results:
                results = [{
                    "title": "No Results",
                    "snippet": f"No search results found for '{input_data.query}'. Try a different search term.",
                    "url": ""
                }]
            
            return results
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"Serper API request failed: {str(e)}")
        except Exception as e:
            raise Exception(f"Web search failed: {str(e)}")