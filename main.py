import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

app = FastAPI(title="Cloud LearnX - Gemini Powered Marker Engine")

# Initialize the Gemini Client
# It automatically picks up GEMINI_API_KEY from your environment
client = genai.Client()

class SubQuestionEvaluation(BaseModel):
    part: str
    marks_awarded: int
    marks_possible: int
    method_marks_awarded: int
    accuracy_marks_awarded: int
    student_method_latex: str
    identified_misconception: str
    examiner_commentary: str

class QuestionMarkerSchema(BaseModel):
    question_id: int
    topic: str
    total_question_marks: int
    total_awarded: int
    sub_parts: List[SubQuestionEvaluation]
    pedagogical_remedy: str

@app.post("/grade-test/", response_model=QuestionMarkerSchema)
def test_grading_logic(student_latex: str, official_rubric: str, question_context: str):
    try:
        system_instruction = (
            "You are a Senior Principal Examiner for Cambridge International Examinations specializing in IGCSE Mathematics. "
            "Evaluate the transcribed student response strictly against the official mark scheme. "
            "Differentiate carefully between Method (M) marks and Accuracy (A) marks. "
            "Follow Follow-Through (F.T.) rules accurately."
        )
        
        user_payload = f"""
        QUESTION SPECIFICATION:
        {question_context}
        
        OFFICIAL MARK SCHEME RUBRIC:
        {official_rubric}
        
        STUDENT TRANSCRIBED RESPONSE (LATEX/MARKDOWN):
        {student_latex}
        """
        
        # Request a structured JSON completion matching our Pydantic schema
        response = client.models.generate_content(
            model='gemini-3.5-flash', # Or 'gemini-1.5-pro' for heavy reasoning
            contents=user_payload,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=QuestionMarkerSchema,
                temperature=0.1 # Keep it low for consistent, strict grading
            ),
        )
        
        # Gemini returns a valid JSON string fitting your model, so we validate it into Pydantic
        return QuestionMarkerSchema.model_validate_json(response.text)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))