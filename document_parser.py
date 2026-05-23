import fitz  # PyMuPDF
import cv2
import numpy as np
import re
import os

def find_question_vertical_intervals(pdf_path: str, target_q: int):
    """
    Scans the entire PDF to find the exact pages and vertical Y-coordinates 
    where a specific question begins and ends.
    Handles Cambridge [marks] boundaries and Edexcel 'Total for' signatures.
    """
    doc = fitz.open(pdf_path)
    
    start_page = None
    ymin = None
    end_page = None
    ymax = None
    
    # 1. Compile Exam Typography Regex Patterns
    start_pattern = re.compile(rf"^\s*{target_q}\s*$|^\s*Question\s*{target_q}\b", re.IGNORECASE)
    edexcel_end_pattern = re.compile(rf"Total\s+for\s+Question\s+{target_q}\b", re.IGNORECASE)
    cambridge_next_q_pattern = re.compile(rf"^\s*{target_q + 1}\s*$|^\s*Question\s*{target_q + 1}\b", re.IGNORECASE)
    
    # Locate where the question starts
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        blocks = page.get_text("blocks")
        for b in blocks:
            text = b[4].strip()
            if start_pattern.match(text):
                start_page = page_idx
                ymin = b[1] - 5  # Give slight upward padding
                break
        if start_page is not None:
            break
            
    if start_page == -1 or ymin is None:
        doc.close()
        return None

    # Locate where the question ends (starting from the start page)
    for page_idx in range(start_page, len(doc)):
        page = doc[page_idx]
        blocks = page.get_text("blocks")
        
        for b in blocks:
            text = b[4].strip()
            # Scenario A: Matches Edexcel closing line on current or subsequent page
            if edexcel_end_pattern.search(text):
                end_page = page_idx
                ymax = b[3] + 5 # Include closing total block boundary
                break
            # Scenario B: Matches Cambridge layout (Next question starts)
            elif cambridge_next_q_pattern.match(text):
                end_page = page_idx
                ymax = b[1] - 15 # Cut right above the next question heading
                break
        if end_page is not None:
            break

    # Scenario C: Cambridge terminal question edge case (No next question text exists)
    if end_page is None:
        # Check the last page where the question was seen for mark brackets
        end_page = start_page
        page = doc[end_page]
        mark_brackets = page.search_for("[")
        if mark_brackets:
            mark_brackets.sort(key=lambda r: r.y1, reverse=True)
            ymax = mark_brackets[0].y1 + 15
        else:
            ymax = page.rect.height - 40 # Standard footer layout cutoff clearance

    doc.close()
    return {
        "start_page": start_page,
        "ymin": ymin,
        "end_page": end_page,
        "ymax": ymax
    }

def check_ink_density(img_matrix, threshold=0.003) -> bool:
    """
    Evaluates whether a cropped image contains real student handwriting.
    Filters out background guidelines, boxes, and white space.
    """
    gray = cv2.cvtColor(img_matrix, cv2.COLOR_BGR2GRAY)
    # Otsu dynamic binarization separates white space from ink marks
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    
    total_pixels = binary.size
    ink_pixels = np.sum(binary == 255)
    density = ink_pixels / total_pixels
    
    return density > threshold

def slice_and_stitch_question(pdf_path: str, target_q: int, output_dir: str) -> str:
    """
    Crops out an isolated question block. Stitches content automatically 
    if the answer workspace flows across page boundaries.
    """
    coords = find_question_vertical_intervals(pdf_path, target_q)
    if not coords:
        print(f"❌ Question {target_q} not found structurally in the document text layer.")
        return None
        
    doc = fitz.open(pdf_path)
    xmin = 35  # Left A4 margin limit clearance
    xmax = doc[0].rect.width - 35  # Right A4 margin limit clearance
    
    fragments = []
    
    # Step 1: Handle Single-Page vs Multi-Page extraction setups
    if coords["start_page"] == coords["end_page"]:
        # Standard workflow: Content is entirely localized to a single page
        page = doc[coords["start_page"]]
        rect = fitz.Rect(xmin, coords["ymin"], xmax, coords["ymax"])
        pix = page.get_pixmap(clip=rect, matrix=fitz.Matrix(3, 3)) # 3x scale up
        
        img_data = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.h, pix.w, pix.n))
        img = cv2.cvtColor(img_data, cv2.COLOR_RGB2BGR) if pix.n == 3 else cv2.cvtColor(img_data, cv2.COLOR_GRAY2BGR)
        fragments.append(img)
    else:
        # Multi-page flow workflow: Question overflows past page cuts
        print(f"🔗 Question {target_q} spans multiple pages. Initializing stitching layer...")
        
        # Crop Top Fragment (From question number down to the absolute bottom margin of page 1)
        p1 = doc[coords["start_page"]]
        r1 = fitz.Rect(xmin, coords["ymin"], xmax, p1.rect.height - 40)
        pix1 = p1.get_pixmap(clip=r1, matrix=fitz.Matrix(3, 3))
        img1_data = np.frombuffer(pix1.samples, dtype=np.uint8).reshape((pix1.h, pix1.w, pix1.n))
        img1 = cv2.cvtColor(img1_data, cv2.COLOR_RGB2BGR) if pix1.n == 3 else cv2.cvtColor(img1_data, cv2.COLOR_GRAY2BGR)
        fragments.append(img1)
        
        # Crop Intermediate Pages completely if it crosses more than 2 pages
        for middle_page_idx in range(coords["start_page"] + 1, coords["end_page"]):
            pm = doc[middle_page_idx]
            rm = fitz.Rect(xmin, 40, xmax, pm.rect.height - 40)
            pixm = pm.get_pixmap(clip=rm, matrix=fitz.Matrix(3, 3))
            imgm_data = np.frombuffer(pixm.samples, dtype=np.uint8).reshape((pixm.h, pix1.w, pixm.n))
            imgm = cv2.cvtColor(imgm_data, cv2.COLOR_RGB2BGR) if pixm.n == 3 else cv2.cvtColor(imgm_data, cv2.COLOR_GRAY2BGR)
            fragments.append(imgm)
            
        # Crop Bottom Fragment (From top margin of the end page down to the layout token end target)
        p2 = doc[coords["end_page"]]
        r2 = fitz.Rect(xmin, 40, xmax, coords["ymax"])
        pix2 = p2.get_pixmap(clip=r2, matrix=fitz.Matrix(3, 3))
        img2_data = np.frombuffer(pix2.samples, dtype=np.uint8).reshape((pix2.h, pix2.w, pix2.n))
        img2 = cv2.cvtColor(img2_data, cv2.COLOR_RGB2BGR) if pix2.n == 3 else cv2.cvtColor(img2_data, cv2.COLOR_GRAY2BGR)
        fragments.append(img2)
        
    doc.close()
    
    # Step 2: Vertically stack (stitch) the slices into one seamless picture canvas matrix
    stitched_canvas = np.vstack(fragments)
    
    # Step 3: Ink density evaluation pass
    is_attempted = check_ink_density(stitched_canvas)
    if not is_attempted:
        print(f"⏩ Question {target_q} has no valid handwriting found. Skipping processing pass.")
        return None
        
    # Save active content to the directory layout
    os.makedirs(output_dir, exist_ok=True)
    file_path = os.path.join(output_dir, f"question_{target_q}.jpg")
    cv2.imwrite(file_path, stitched_canvas)
    print(f"💾 Saved cleanly isolated workspace: {file_path}")
    return file_path

# --- Operational Local Verification Pipeline Mock ---
if __name__ == "__main__":
    # Change this target to path your exam file to test it locally
    MOCK_PDF = "/home/seven/projects/cloud-learnx-marker/2025 Nov Paper.pdf" 
    OUTPUT_DIRECTORY = "extracted_questions"
    
    if os.path.exists(MOCK_PDF):
        print(f"🚀 Initializing Dynamic Parsing Run on file: {MOCK_PDF}")
        # Loop through a theoretical 5-question assignment block to index content
        for q_num in range(1, 6):
            slice_and_stitch_question(pdf_path=MOCK_PDF, target_q=q_num, output_dir=OUTPUT_DIRECTORY)
    else:
        print(f"ℹ️ Script ready. Place an exam file named '{MOCK_PDF}' here to execute the batch extraction process.")