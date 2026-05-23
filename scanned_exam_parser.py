import pytesseract
from pdf2image import convert_from_path
import cv2
import numpy as np
import re
import os

# If you are on Windows, uncomment the line below and point it to your tesseract.exe location:
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def parse_scanned_pdf(pdf_path: str, target_q: int, output_dir: str):
    """
    Hardened layout-aware scanner that restricts number matching to the 
    left-hand column margins to avoid false positive triggers.
    """
    print(f"📖 Reading scanned pages from {pdf_path}...")
    pages = convert_from_path(pdf_path, dpi=200)
    
    start_page_idx = None
    ymin = None
    end_page_idx = None
    ymax = None
    
    # 1. Stricter Regex: Ensures it captures clean number entries
    start_pattern = re.compile(rf"^\s*{target_q}[\.\)]?\s*$")
    cambridge_next_pattern = re.compile(rf"^\s*{target_q + 1}[\.\)]?\s*$")
    edexcel_end_pattern = re.compile(rf"Total\s+for\s+Question\s+{target_q}\b", re.IGNORECASE)
    
    page_matrices = []
    
    for idx, page_img in enumerate(pages):
        img_cv = cv2.cvtColor(np.array(page_img), cv2.COLOR_RGB2BGR)
        page_matrices.append(img_cv)
        img_width = img_cv.shape[1]
        
        # Define the Left Margin Column bounding zone (usually first 15% of page width)
        left_margin_limit = int(img_width * 0.15)
        
        ocr_data = pytesseract.image_to_data(img_cv, output_type=pytesseract.Output.DICT)
        n_boxes = len(ocr_data['text'])
        
        for i in range(n_boxes):
            text = ocr_data['text'][i].strip()
            if not text:
                continue
                
            token_left = ocr_data['left'][i]
            token_top = ocr_data['top'][i]
            token_height = ocr_data['height'][i]
            
            # --- FIND START BOUNDARY ---
            if start_page_idx is None:
                # Core Guardrail: The question number MUST live inside the left margin column
                if start_pattern.match(text) and token_left < left_margin_limit:
                    start_page_idx = idx
                    ymin = token_top - 15  # Include padding above question row
                    print(f"🎯 Verified Question {target_q} Start -> Page {idx + 1}, Y: {ymin}")
                    continue
            
            # --- FIND END BOUNDARY ---
            if start_page_idx is not None and end_page_idx is None:
                # Rule A: Check for explicit Edexcel trailer line anywhere on the canvas
                if edexcel_end_pattern.search(text):
                    end_page_idx = idx
                    ymax = token_top + token_height + 20
                    print(f"🏁 Verified Edexcel Endpoint -> Page {idx + 1}, Y: {ymax}")
                    break
                    
                # Rule B: Check for next question number - MUST also live inside left margin column
                if cambridge_next_pattern.match(text) and token_left < left_margin_limit:
                    # If it's on the same page as the start, it sets the floor
                    # If it's on a later page, this means the question ended on the PREVIOUS page
                    if idx > start_page_idx:
                        end_page_idx = idx - 1
                        ymax = page_matrices[end_page_idx].shape[0] - 60 # Set to end of previous page
                    else:
                        end_page_idx = idx
                        ymax = token_top - 20 # Cut right above next question block
                    print(f"🏁 Verified Cambridge Endpoint -> Page {end_page_idx + 1}, Y: {ymax}")
                    break

    # Fallback logic if the next question isn't found
    if start_page_idx is not None and end_page_idx is None:
        end_page_idx = start_page_idx
        ymax = page_matrices[end_page_idx].shape[0] - 60
        print(f"⚠️ Trailing boundary fallback invoked on Page {end_page_idx + 1}, Y: {ymax}")

    if start_page_idx is None:
        print(f"❌ Question {target_q} skipped: structural column signature not found.")
        return None

    # 2. Slice and stitch logic based on narrowed coordinates
    fragments = []
    xmin = 40
    xmax = img_width - 40

    if start_page_idx == end_page_idx:
        # Prevent negative cropping dimensions
        final_ymin = max(0, ymin)
        final_ymax = min(page_matrices[start_page_idx].shape[0], ymax)
        if final_ymin < final_ymax:
            cropped = page_matrices[start_page_idx][final_ymin:final_ymax, xmin:xmax]
            fragments.append(cropped)
    else:
        # Standard multi-page crop flow
        fragments.append(page_matrices[start_page_idx][ymin:, xmin:xmax])
        for m_idx in range(start_page_idx + 1, end_page_idx):
            fragments.append(page_matrices[m_idx][:, xmin:xmax])
        if ymax > 0:
            fragments.append(page_matrices[end_page_idx][0:ymax, xmin:xmax])

    if not fragments:
        return None

    stitched_canvas = np.vstack(fragments)

    # 3. Output extraction data
    os.makedirs(output_dir, exist_ok=True)
    save_path = os.path.join(output_dir, f"question_{target_q}.jpg")
    cv2.imwrite(save_path, stitched_canvas)
    print(f"💾 Clean snippet generated: {save_path}\n")
    return save_path

if __name__ == "__main__":
    TEST_FILE = "2025 Nov Paper.pdf" 
    OUTPUT_DIRECTORY = "extracted_scans"
    
    # MAX_LOOK_AHEAD defines how many consecutive missing numbers to check 
    # before deciding we are truly at the end of the examination paper.
    MAX_LOOK_AHEAD = 3 
    
    if os.path.exists(TEST_FILE):
        print(f"🚀 Initializing Resilient Dynamic Scanner on: {TEST_FILE}")
        
        q_num = 1
        look_ahead_counter = 0
        total_extracted = 0
        
        while True:
            print(f"🔍 Searching for Question {q_num}...")
            
            # Execute our parsing run
            saved_path = parse_scanned_pdf(TEST_FILE, target_q=q_num, output_dir=OUTPUT_DIRECTORY)
            
            if saved_path is not None:
                # We found a valid question! Reset the look-ahead safety tracker
                print(f"✅ Finished processing Question {q_num}.\n" + "-"*40)
                look_ahead_counter = 0
                total_extracted += 1
            else:
                # Question skipped (maybe a poor scan or blurred margin layout)
                look_ahead_counter += 1
                print(f"⚠️ Warning: Question {q_num} was skipped/not found.")
                print(f"🔄 Look-ahead active: Checking next targets ({look_ahead_counter}/{MAX_LOOK_AHEAD})...\n" + "-"*40)
            
            # If we hit consecutive failures equal to our look-ahead limit, we stop.
            if look_ahead_counter >= MAX_LOOK_AHEAD:
                print(f"🏁 Stopped scanning. Missed {MAX_LOOK_AHEAD} consecutive numbers. End of booklet reached.")
                break
                
            q_num += 1  # Keep moving forward to the next index no matter what!
            
        print(f"🎉 Fully automated resilient batch extraction complete!")
        print(f"📊 Total active questions successfully extracted: {total_extracted}")
    else:
        print(f"File '{TEST_FILE}' not found. Please verify the path.")