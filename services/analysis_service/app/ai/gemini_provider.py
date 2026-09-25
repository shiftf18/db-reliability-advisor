import json

from google import genai

from ..contracts.models import AnalysisPackage
from .base import AIInterpretation, AIProvider
from .prompts import SYSTEM_PROMPT


class GeminiAIProvider(AIProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required when AI_PROVIDER=gemini")
        if not model:
            raise ValueError("GEMINI_MODEL is required when AI_PROVIDER=gemini")
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def analyze(self, package: AnalysisPackage) -> AIInterpretation:
        response = self.client.models.generate_content(
            model=self.model,
            contents=(
                f"{SYSTEM_PROMPT}\nAnalysis package (Contract B):\n"
                f"{package.model_dump_json(by_alias=True, exclude_none=True)}"
            ),
            config={
                "response_mime_type": "application/json",
                "response_json_schema": AIInterpretation.model_json_schema(),
            },
        )
        if not response.text:
            raise RuntimeError("Gemini returned an empty interpretation")
        return AIInterpretation.model_validate(json.loads(response.text))
