import fitz  # PyMuPDF
import cv2
import numpy as np
import os

def slice_exam_question(pdf_path: str, page_num: int, start_token: str, end_token: str, output_img_path: str) -> bool:
    """
    Locates an Edexcel/Cambridge question block on a page, crops the working area,
    saves it locally, and returns True if the student wrote an answer (False if skipped).
    """
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    
    # 1. Locate the structural tokens on the page coordinate space
    start_matches = page.search_for(start_token)
    end_matches = page.search_for(end_token)
    
    if not start_matches or not end_matches:
        print(f"⚠️ Could not find bounding structural blocks on page {page_num + 1}")
        doc.close()
        return False
        
    # Extract vertical positions (y-coordinates)
    # y1 is the bottom edge of the start token text box
    ymin = start_matches[0].y1 + 10  # Add small padding below question prompt
    # y0 is the top edge of the total marks footer line
    ymax = end_matches[0].y0 - 10    # Subtract padding above footer
    
    # Define document page width boundaries (A4 standard printable canvas limits)
    page_width = page.rect.width
    xmin = 35                  # Left margin clearance
    xmax = page_width - 35     # Right margin clearance
    
    # Ensure our bounding box values are mathematically valid
    if ymin >= ymax:
        print(f"⚠️ Invalid clipping rectangle dimensions computed on page {page_num + 1}")
        doc.close()
        return False
        
    # 2. Slice the exact canvas crop zone
    crop_rect = fitz.Rect(xmin, ymin, xmax, ymax)
    
    # Render the area to a high-density crisp pixel map image
    # Matrix(3, 3) increases DPI by 3x so handwriting stays razor sharp for future OCR stages
    pix = page.get_pixmap(clip=crop_rect, matrix=fitz.Matrix(3, 3))
    
    # Convert pixmap into a temporary in-memory format that OpenCV can check
    img_data = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.h, pix.w, pix.n))
    img_bgr = cv2.cvtColor(img_data, cv2.COLOR_RGB2BGR) if pix.n == 3 else cv2.cvtColor(img_data, cv2.COLOR_GRAY2BGR)
    
    doc.close()
    
    # 3. Local Ink Analysis: Verify if the student attempted the problem
    # Convert to grayscale and isolate ink content
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    
    # Calculate density ratio
    total_pixels = binary.size
    ink_pixels = np.sum(binary == 255)
    ink_density = ink_pixels / total_pixels
    
    # If the ink density is extremely low, the box contains only white space/empty guidelines
    # Edexcel guidelines/grids generally produce a negligible threshold once thresholded
    if ink_density < 0.003: 
        print(f"⏩ Question block '{start_token}' is completely unattempted. Skipping processing layer.")
        return False
        
    # Save the file to your disk since it contains active handwriting
    cv2.imwrite(output_img_path, img_bgr)
    print(f"💾 Successfully cropped and stored: {output_img_path} (Ink Density: {ink_density:.4f})")
    return True