import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
from dotenv import load_dotenv
from openai import OpenAI

# Load secret API keys from the .env file
load_dotenv()

app = FastAPI(title="Cloud LearnX - AI Marker Engine")

# Initialize the OpenAI Client
# This will automatically look for the OPENAI_API_KEY environment variable
client = OpenAI()

# Define the exact structure we want the AI to return
class SubQuestionEvaluation(BaseModel):
    part: str                  # e.g., "a", "b(i)"
    marks_awarded: int
    marks_possible: int
    method_marks_awarded: int
    accuracy_marks_awarded: int
    student_method_latex: str  # The transcribed steps the student took
    identified_misconception: str  # e.g., "Sign error during algebraic expansion"
    examiner_commentary: str

class QuestionMarkerSchema(BaseModel):
    question_id: int
    topic: str                 # e.g., "Sequences", "Quadratic Functions"
    total_question_marks: int
    total_awarded: int
    sub_parts: List[SubQuestionEvaluation]
    pedagogical_remedy: str    # Actionable advice personalized for this specific student

@app.post("/grade-test/", response_model=QuestionMarkerSchema)
def test_grading_logic(student_latex: str, official_rubric: str, question_context: str):
    """
    Simulates the core AI evaluation step using text/LaTeX input
    before we plug in the image-processing layers.
    """
    try:
        system_instruction = (
            "You are a Senior Principal Examiner for Cambridge International Examinations specializing in IGCSE Mathematics. "
            "Evaluate the transcribed student response strictly against the official mark scheme. "
            "Differentiate carefully between Method (M) marks—awarded for correct algebraic setups—and Accuracy (A) marks. "
            "If a student makes an early arithmetic slip but applies the correct subsequent method, follow 'Own Error' (O.E.) "
            "or 'Follow Through' (F.T.) rules accurately. Do not award marks for correct final answers achieved through invalid logic."
        )
        
        user_payload = f"""
        QUESTION SPECIFICATION:
        {question_context}
        
        OFFICIAL MARK SCHEME RUBRIC:
        {official_rubric}
        
        STUDENT TRANSCRIBED RESPONSE (LATEX/MARKDOWN):
        {student_latex}
        """
        
        # Enforce strict structured output matching our Pydantic schema
        completion = client.beta.chat.completions.parse(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_payload}
            ],
            response_format=QuestionMarkerSchema
        )
        
        return completion.choices[0].message.parsed

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))