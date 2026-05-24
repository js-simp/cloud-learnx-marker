import os
import json
import fitz  # PyMuPDF
from pdf2image import convert_from_path
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import List, Optional
import time

from dotenv import load_dotenv
load_dotenv()

# =====================================================================
# 1. PYDANTIC STRUCTURED SCHEMAS (Enforced at the API Layer)
# =====================================================================

class QuestionMapping(BaseModel):
    question_number: int = Field(description="The structural main integer question number.")
    pages: List[int] = Field(description="1-based page numbers where this question's layout/workspace exists.")

class ExamPaperStructure(BaseModel):
    paper_title: str = Field(description="Name, year, or session code of the exam booklet.")
    mappings: List[QuestionMapping]

class SubPartGrade(BaseModel):
    part_identifier: str = Field(description="e.g., 'a', 'b(i)', 'c'")
    marks_awarded: int
    marks_possible: int
    method_marks_earned: int = Field(description="Marks earned for valid algebraic or mathematical methodology layout step paths.")
    accuracy_marks_earned: int = Field(description="Marks earned for calculation/numerical accuracy.")
    identified_misconception: Optional[str] = Field(description="Specific math concept error classification if any. Null if perfect.")
    detailed_critique: str = Field(description="Constructive critique detailing exactly where the student script deviated from rubric logic.")

class AcademicEvaluationMatrix(BaseModel):
    question_number: int
    total_score: int
    max_score: int
    topic_classification: str = Field(description="The underlying mathematics topic domain (e.g., 'Trigonometry', 'Vectors', 'Quadratic Equations').")
    sub_parts: List[SubPartGrade]
    pedagogical_remedial_strategy: str = Field(description="Actionable, targeted revision instructions written for the student.")

# =====================================================================
# 2. CORE PIPELINE IMPLEMENTATION FUNCTIONS
# =====================================================================

def execute_ai_layout_segmentation(pdf_path: str, client: genai.Client) -> ExamPaperStructure:
    """
    Converts a multi-page exam PDF to background images, asks Gemini Pro 
    to map the structure, and outputs a clean structural JSON blueprint.
    """
    print("⏳ Stage 1: Converting document vector paths to frame buffers for layout visualization...")
    images = convert_from_path(pdf_path, dpi=70)
    
    temp_files = []
    for idx, page_img in enumerate(images):
        temp_path = f"cache_scan_page_{idx + 1}.jpg"
        page_img.save(temp_path, "JPEG")
        temp_files.append(temp_path)
        
    print("📤 Stage 1: Initializing secure Gemini Session Data stream context uploads...")
    uploaded_payloads = []
    for path in temp_files:
        blob = client.files.upload(file=path)
        uploaded_payloads.append(blob)
        
    analysis_prompt = """
    Analyze these chronological pages of a scanned student mathematics exam paper script.
    Identify every single major question heading index number (1, 2, 3...) and state every 1-based page number where that question block or answer workspace area spans.
    
    Rules:
    - If Question 3 spans across both Page 4 and Page 5, register its page array list explicitly as [4, 5].
    - Focus strictly on core structural question keys. Ignore subpart letters like (a) or (b) when defining keys.
    - Be completely immune to messy ink scribbles or faint layout printing from Edexcel or Cambridge booklets.
    """
    
    print("🧠 Stage 1: Running deep multimodal layout parsing via gemini-2.5-pro...")
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=[*uploaded_payloads, analysis_prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ExamPaperStructure,
            temperature=0.1
        ),
    )
    
    for path in temp_files:
        if os.path.exists(path):
            os.remove(path)
            
    return ExamPaperStructure.model_validate_json(response.text)


def segment_pdf_by_blueprint(pdf_path: str, blueprint: ExamPaperStructure, output_dir: str) -> List[str]:
    """
    Takes the structured layout schema from Gemini and cleanly splits the actual 
    high-res PDF pages into individual single-question sub-PDF vectors.
    """
    print("\n✂️ Stage 2: Initializing high-precision programmatic vector slicing matrix...")
    os.makedirs(output_dir, exist_ok=True)
    
    source_doc = fitz.open(pdf_path)
    generated_question_paths = []
    
    for mapping in blueprint.mappings:
        q_num = mapping.question_number
        pages_to_extract = mapping.pages
        
        if not pages_to_extract:
            print(f"  ⚠️ Skipping Question {q_num}: Blueprint assigned zero pages.")
            continue
            
        split_doc = fitz.open()
        pages_successfully_inserted = 0
        
        for page_num in pages_to_extract:
            zero_based_index = page_num - 1
            if 0 <= zero_based_index < len(source_doc):
                split_doc.insert_pdf(source_doc, from_page=zero_based_index, to_page=zero_based_index)
                pages_successfully_inserted += 1
                
        # 🛡️ THE FIX: Guard condition to prevent saving empty document frames
        if pages_successfully_inserted == 0:
            print(f"  ⚠️ Skipping Question {q_num}: Valid page boundaries could not be located in source.")
            split_doc.close()
            continue
                
        output_filepath = os.path.join(output_dir, f"question_{q_num}.pdf")
        split_doc.save(output_filepath)
        split_doc.close()
        
        print(f"  💾 Extracted Pristine Vector Asset -> {output_filepath}")
        generated_question_paths.append(output_filepath)
        
    source_doc.close()
    return generated_question_paths


def grade_with_official_pdf_scheme(
    student_question_pdf_path: str, 
    official_scheme_pdf_path: str, 
    question_number: int, 
    client: genai.Client
) -> AcademicEvaluationMatrix:
    """
    Passes both the student's handwritten sub-PDF and the macro official 
    marking scheme PDF to Gemini to dynamically trace criteria blocks.
    """
    print(f"🔬 Stage 3: Digitally auditing Question {question_number} against the official PDF schema...")
    
    student_blob = client.files.upload(file=student_question_pdf_path)
    scheme_blob = client.files.upload(file=official_scheme_pdf_path)
    
    system_instruction = """
    You are an elite Chief Assistant Principal Examiner for International Secondary Mathematics Examinations.
    Your single objective is to extract the correct question evaluation criteria from the official mark scheme document, 
    and apply it with high objective fidelity onto the student's handwritten working steps.
    """
    
    prompt = f"""
    CONTEXT ASSIGNMENT:
    Target Evaluation Target: Question {question_number}
    
    INPUT ASSETS:
    1. Associated Document: Clear handwritten workspace page(s) containing the student's calculation steps.
    2. Reference Scheme Document: The full institutional marking scheme document array.
    
    INSTRUCTIONS:
    - Locate the exact marking rubric boundaries for Question {question_number} inside the provided reference scheme.
    - Audit the student's method paths step-by-step. Assess whether they deserve Method (M) marks or Accuracy (A) marks.
    - Output your detailed diagnostic findings inside the required structural data format.
    """
    
    # FIX: Updated to correct model identification target identifier
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=[student_blob, scheme_blob, prompt],
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=AcademicEvaluationMatrix,
            temperature=0.0  
        ),
    )
    
    return AcademicEvaluationMatrix.model_validate_json(response.text)

# =====================================================================
# 3. UNIFIED PIPELINE TEST DRIVER
# =====================================================================
if __name__ == "__main__":
    SOURCE_PAPER_PDF = "2025 Nov Paper.pdf"
    WORKSPACE_CACHE_DIR = "isolated_question_vectors"
    OFFICIAL_SCHEME_PDF = "IGCSE_Nov_2025_marking_scheme.pdf" 

    if "GEMINI_API_KEY" not in os.environ:
        print("❌ Error Execution Aborted: Missing 'GEMINI_API_KEY' in local environment variables.")
    elif not os.path.exists(SOURCE_PAPER_PDF):
        print(f"❌ Error Target Asset Missing: Could not locate the file '{SOURCE_PAPER_PDF}' in working dir.")
    elif not os.path.exists(OFFICIAL_SCHEME_PDF):
        print(f"❌ Error Target Asset Missing: Could not locate the file '{OFFICIAL_SCHEME_PDF}' in working dir.")
    else:
        print(f"🏁 Starting End-to-End Multimodal AI Exam Architecture Pipeline execution...")
        
        ai_client = genai.Client()
        
        # PHASE 1: Visually map out layout configurations using Gemini Pro 
        layout_blueprint = execute_ai_layout_segmentation(SOURCE_PAPER_PDF, ai_client)
        print(f"✅ Layout Architecture Decoded! Title discovered: '{layout_blueprint.paper_title}'")
        
        # PHASE 2: Slice multi-page script into crisp single-question isolated PDF files
        question_files = segment_pdf_by_blueprint(SOURCE_PAPER_PDF, layout_blueprint, WORKSPACE_CACHE_DIR)
        
        print(f"\n⚡ Passing isolated files down to the automated grading agent matrix...")
        final_exam_report_summary = []
        
        # PHASE 3: Iteratively feed isolated files to the AI grading matrix
        # Using enumerate to dynamically provide the precise structural question identifier matching the index loops
        for idx, q_path in enumerate(question_files, start=1):
            try:
                # FIX: Added the missing positional argument (idx) so parameters match definition bounds perfectly
                grading_matrix = grade_with_official_pdf_scheme(q_path, OFFICIAL_SCHEME_PDF, idx, ai_client)
                final_exam_report_summary.append(grading_matrix.model_dump())
                
                print(f"   ✨ Successfully graded Question {grading_matrix.question_number}!")
                print(f"      Score: {grading_matrix.total_score}/{grading_matrix.max_score} | Topic: {grading_matrix.topic_classification}")
                print(f"      Advice: {grading_matrix.pedagogical_remedial_strategy}\n" + "-"*60)
                print("⏳ Sleeping 35 seconds to preserve API free-tier RPM limits...")
                time.sleep(35)
            except Exception as e:
                print(f"   ⚠️ Could not automatically process {q_path} due to error: {e}")
                
        print("\n🎉 Full Pipeline Test Concluded. Output analytical object ready for database persistence syncing!")