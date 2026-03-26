import os
import re
import json
import uuid
import fitz
import openai
import datetime 
import time
import faiss
import numpy as np
from werkzeug.utils import secure_filename
import google.generativeai as genai
from flask import current_app
from models import db, Tender, Document, RiskAssessment, Risk, QAInteraction, Product
from models import BidderQuestionsSet, BidderQuestion, Constraint, ServiceProductDefinition
import PyPDF2


openai.api_key = os.getenv("OPENAI_API_KEY")

# In-memory vector store (for demo; you can persist to disk if needed)
vector_stores = {}

# Initialize Gemini API
def init_gemini():
    genai.configure(api_key=current_app.config['GEMINI_API_KEY'])
    return genai.GenerativeModel('gemini-2.5-flash')

# File Handling
def extract_text_from_file(file_path, file_extension):
    if file_extension == '.pdf':
        try:
            with fitz.open(file_path) as doc:
                text = "\n".join([page.get_text() for page in doc])
            return text
        except Exception as e:
            print(f"[ERROR] Failed to extract PDF text with PyMuPDF: {e}")
            return ""
    elif file_extension == '.txt':
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    else:
        raise ValueError(f"Unsupported file type: {file_extension}")

def save_uploaded_file(file):
    unique_filename = secure_filename(f"{uuid.uuid4()}_{file.filename}")
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
    file.save(file_path)
    file_size = os.path.getsize(file_path)
    file_extension = os.path.splitext(file.filename)[1].lower()
    
    text_content = extract_text_from_file(file_path, file_extension)
    
    return {
        'filename': unique_filename,
        'original_filename': file.filename,
        'file_path': file_path,
        'file_type': file_extension[1:],
        'file_size': file_size,
        'content_text': text_content
    }

def extract_all_pdf_links(pdf_path):
    """
    Extract ALL hyperlinks from PDF using PyPDF2
    Returns list of unique URLs
    """
    try:
        with open(pdf_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            links = set()  # Use set to avoid duplicates
            
            for page in reader.pages:
                if '/Annots' in page:
                    for annot in page['/Annots']:
                        annot_obj = annot.get_object()
                        if '/A' in annot_obj:
                            link = annot_obj['/A'].get('/URI')
                            if link and link.startswith(('http://', 'https://')):
                                links.add(link)
            
            return list(links)
            
    except Exception as e:
        print(f"[ERROR] Failed to extract PDF links: {e}")
        return []

# AI Analysis Functions
def extract_tender_overview(text_content, pdf_path=None):
    """Enhanced tender overview extraction with focused field set and formatted output"""
    print(f"[DEBUG] Starting tender overview extraction", flush=True)
    
    model = init_gemini()
    original_length = len(text_content)
    print(f"[DEBUG] Document length: {original_length} characters", flush=True)
    
    # Updated field keywords for only the selected fields
    field_keywords = {
        'tender_number': [
            'tender no', 'tender number', 'rfp no', 'rfq no', 'notice no', 'gem/', 'tender id',
            'reference no', 'procurement no', 'bid no', 'invitation no', 'nit no', 'tender enquiry no', 'ca no', 'quotation id'
        ],
        'title': [
            'tender title', 'project title', 'work title', 'bid title', 'contract title',
            'tender name', 'project name', 'work name', 'bid name', 'contract name'
        ],
        'organization_details': [
            'issued by', 'tender issuing authority', 'procuring entity', 'buyer', 'purchaser',
            'organization', 'department', 'ministry', 'authority', 'issued on behalf'
        ],
        'due_date': [
            'due date', 'submission date', 'closing date', 'last date', 'deadline',
            'submit by', 'closing time', 'tender closing', 'bid submission',
            'final submission', 'tender due', 'closing on'
        ],
        'bid_opening_date': [
            'bid opening', 'opening of bids', 'technical bid opening', 
            'financial bid opening', 'price bid opening', 'opening date'
        ],
        'bid_offer_validity': [
            'bid validity', 'offer validity', 'tender validity', 
            'valid for', 'validity period', 'validity of bid', 
            'offer to remain valid', 'validity days'
        ],
        'emd_amount': [
            'emd', 'earnest money', 'bid security', 'tender security', 'security deposit',
            'bid deposit', 'performance guarantee', 'bank guarantee', 'dd', 'demand draft'
        ],
        'estimated_cost': [
            'estimated cost', 'project cost', 'approximate cost', 
            'estimated value', 'value of work', 'tender value', 
            'budget estimate', 'approx value'
        ],
        'qualification_criteria': [
            'eligibility', 'qualification', 'qualified bidder', 'technical qualification',
            'minimum turnover', 'experience', 'similar work', 'past performance',
            'financial capacity', 'technical capacity', 'prequalification', 'eligibility criteria'
        ],
        'question_deadline': [
            'clarification', 'query', 'question', 'doubt', 'pre-bid meeting',
            'queries deadline', 'clarification deadline', 'last date for queries',
            'questions by', 'clarifications by', 'pre-bid conference'
        ],
        'reverse_auction': [
            'reverse auction', 'e-auction', 'auction', 'tie', 'L1', 'GeM',
            'lowest bid', 'bid tie', 'auction process', 'e-bidding', 'dutch auction'
        ],
        'rejection_criteria': [
            'rejection', 'disqualification', 'invalid bid', 'non-responsive',
            'rejected if', 'disqualified', 'elimination criteria', 'grounds for rejection',
            'bid rejection', 'non-compliance'
        ],
        'msme_preferences': [
            'msme', 'micro small medium', 'ssi', 'small scale', 'purchase preference',
            'price preference', 'msme benefit', 'small enterprise', 'startup',
            'womens entrepreneurship', 'sc/st entrepreneur'
        ],
        'border_country_clause': [
            'border', 'china', 'pakistan', 'sharing land border', 'security clearance',
            'country restriction', 'banned countries', 'prohibited countries',
            'prior security clearance', 'competent authority approval'
        ],
        'technical_specifications': [
            'technical specification', 'technical requirement', 'scope of work',
            'deliverables', 'product specification', 'service requirement'
        ],
        'payment_terms': [
            'payment', 'payment terms', 'payment schedule', 'payment milestone',
            'advance payment', 'invoice', 'billing', 'payment condition'
        ],
        'performance_security': [
            'performance security', 'performance guarantee', 'performance bond',
            'contract security', 'post award security'
        ],
        'evaluation_criteria': [
            'evaluation', 'selection criteria', 'technical evaluation',
            'commercial evaluation', 'scoring', 'weightage', 'evaluation methodology'
        ],
        'scope_of_work': [
            'scope of work', 'scope of supply', 'work scope', 'deliverables',
            'project scope', 'work description', 'service scope'
        ],
        'performance_standards': [
            'performance standard', 'quality standard', 'performance requirement',
            'service level', 'quality requirement', 'technical standard'
        ],
        'documentation_requirements': [
            'documents required', 'documentation', 'certificates required',
            'supporting documents', 'annexures', 'attachments', 'forms to be submitted'
        ],
        'products_table': [
            'bill of quantity', 'boq', 'items to be supplied', 'products to be supplied',
            'list of items', 'schedule of requirements', 'material list', 'product list',
            'items required', 'goods to be supplied', 'deliverables', 'scope of supply',
            'item description', 'product description', 'quantity required', 'delivery schedule',
            'consignee', 'delivery address', 'specification', 'technical specification', 'no of units'
        ]
    }
    
    # Enhanced content processing with prioritized sections
    max_content_length = 120000
    
    # Extract prioritized sections based on field keywords
    prioritized_sections = extract_prioritized_sections(text_content, field_keywords)
    
    # Combine prioritized sections with document structure
    if prioritized_sections:
        priority_content = "\n".join(prioritized_sections[:12])  # Top 12 sections
        remaining_length = max_content_length - len(priority_content)
        main_content = text_content[:remaining_length] if remaining_length > 0 else ""
        enhanced_content = priority_content + "\n\n--- FULL DOCUMENT CONTENT ---\n" + main_content
    else:
        enhanced_content = text_content[:max_content_length]
    
    print(f"[DEBUG] Enhanced content length: {len(enhanced_content)} characters", flush=True)

    # Extract ALL hyperlinks from PDF if path provided
    all_hyperlinks = []
    if pdf_path and os.path.exists(pdf_path):
        print(f"[DEBUG] Extracting hyperlinks from PDF: {pdf_path}")
        all_hyperlinks = extract_all_pdf_links(pdf_path)
        print(f"[DEBUG] Found {len(all_hyperlinks)} hyperlinks in PDF")
    
    # Updated prompt with enhanced formatting instructions and better JSON requirements
    prompt = f"""You are an expert tender document analyzer. Extract information from the document and return ONLY a valid JSON object.

CRITICAL JSON REQUIREMENTS:
- Return ONLY the JSON object, no other text before or after
- Use proper JSON escaping (\\n for newlines, \\" for quotes)
- Do not include trailing commas
- Ensure all field values are strings
- Do not use markdown code blocks

Extract these fields from the tender document:

{{
    "tender_number": "Complete tender reference number. Don't abbreviate. Get exact tneder ID from document (e.g., 'GEM/2023/B/3673496', '2025_MES_736213_2', '8742/KKD/E8', 'GE/HAL-56/2025-26', 'H6A1Z43625')",
    "title": "Extract the title from this document (e.g., 'Procurement of Ball Valves on ARC Basis')",
    "organization_details": "Full issuing authority name and details",
    "due_date": "Submission deadline with date and time",
    "bid_opening_date": "Bid opening date and time",
    "bid_offer_validity": "Get the bid offer validity in days and also calculate the exact validity\
        end date by adding those days to the tender end date. Format: '120 Days (Valid Until: DD-MM-YYYY)'.", 
    "emd_amount": "EMD/security deposit amount and details. The currency in Indian format — \
        use the 'Rs.' prefix and Indian-style comma placement (e.g., 'Rs. 2,30,234.00' or 'Rs. 1,05,00,000.00').",
    "estimated_cost": "Estimated Cost/Estimated Bid Value if available and the currency in Indian format — \
        use the 'Rs.' prefix and Indian-style comma placement (e.g., 'Rs. 2,30,234.00' or 'Rs. 1,05,00,000.00').",
    "question_deadline": "Last date and time for submitting queries or clarifications. Also get \
        Email address(es) for submitting pre-bid queries and clarifications",
    "performance_security": "Performance guarantee requirements",
    "payment_terms": "Payment schedule and conditions",
    "qualification_criteria": "Bidder qualification requirements",
    "evaluation_criteria": "Bid evaluation methodology",
    "technical_specifications": "Technical requirements and standards",
    "scope_of_work": "Work scope and deliverables",
    "performance_standards": "Quality and performance requirements",
    "reverse_auction": "Auction process details if applicable",
    "msme_preferences": "MSME benefits and preferences",
    "border_country_clause": "Restrictions for border countries",
    "rejection_criteria": "Bid rejection conditions",
    "documentation_requirements": "Required documents for submission",
    "products_table": [
        {{
            "product_name": (
                "List names of all products/product numbers, materials, or equipment the supplier must provide, "
                "from sections like BOQ, Scope of Work, or Technical Specs. "
                "Return product/item/services names with —  specs, sizes or models. "
                "Example: 'LED Light Fitting 20W 230V', not 'LED Light Fitting'. "
            )
            "quantity": "Extract the exact quantity/no of units mentioned for this item/product/service.,
            "delivery_days": "Extract delivery timeline, completion period, or project duration \
                mentioned for this item/product/service. (e.g., '30 Days', '3 Months').",
            "consignee_name": "Extract the recipient name, consignee, end user, or department \
                mentioned for delivery. If multiple, list them separated by commas.",
            "delivery_address": "Extract the complete delivery address, location, or site mentioned \
                for this item/product/service. Include city, state, and specific location details.",
            "specification_link": (
                "Analyze hyperlinks extracted from a tender PDF to determine if any of them "
                "correspond specifically to this product's specifications, BOQ, or technical details. "
                "Below are all hyperlinks found in the document: "
                f"{', '.join(all_hyperlinks) if all_hyperlinks else 'No hyperlinks found in document'}.\n\n"
                "TASK:\n"
                "1. Carefully review all the given hyperlinks.\n"
                "2. If **any** hyperlink appears related to the product’s exact model, size, specification sheet, "
                "technical data, or BOQ reference — include **only those** URLs.\n"
                "3. Only if absolutely **no hyperlinks are available at all**, return this default message exactly:\n"
                "'Documents not available'.\n\n"
                "OUTPUT FORMAT:\n"
                "- Return a comma-separated list of URLs if links exist.\n"
                "- Return the default message only if there are truly no links."
            )
        }},
        "additional_details": (
            "Extract any remaining important details, conditions, clauses, or notes from the tender that have not been covered "
            "in the fields above. Focus on mandatory, compliance-related, or bidder-critical information "
            "\\n\\nBelow are ALL hyperlinks found in the document: "
            f"{', '.join(all_hyperlinks) if all_hyperlinks else 'No hyperlinks found in document'}."
            "\\n\\nAlso review all hyperlinks above, and EXCLUDE any that were already included in any product’s "
            "'specification_link' field. For all remaining (unused) links, include them here with short, meaningful labels "
            "based on filename or nearby text context (e.g., 'Annexure', 'BOQ', 'Corrigendum', 'Technical Format', etc.). "
            "\\n\\nReturn a concise summary of the remaining details and a labeled list of these unused links. "
            "If nothing remains, return 'No additional details found.'"
            "Header for the links section must be 'Documents'. Don't use bold letters."
        )
    ]
}}

For each field:
- If information is found, extract it clearly
- If not found, use "Not specified in document"
- For complex information, use \\n to separate points
- Keep field values concise but complete
- Use ** for emphasis within strings when needed
- If multiple items/products/services exist, include all of them in the "products_table" array

Document content:
{enhanced_content}

Return only the JSON object:"""


    try:
        print("[DEBUG] Generating AI response...", flush=True)
        # Primary extraction attempt
        response = model.generate_content(prompt, generation_config={
            'temperature': 0
        })
        
        try:
            text_response = response.text
            print(f"[DEBUG] Received response of length: {len(text_response)}", flush=True)
            print(f"[DEBUG] First 500 chars of response: {text_response[:500]}", flush=True)
            
            # Use robust JSON parsing instead of simple json.loads
            overview_data = robust_json_parse(text_response)
            
            # Ensure all required fields are present
            required_fields = [
                "tender_number", "title", "organization_details", "due_date", "bid_opening_date", "bid_offer_validity", 
                "question_deadline", "emd_amount", "estimated_cost", "performance_security", "payment_terms", 
                "qualification_criteria", "evaluation_criteria", "technical_specifications", "scope_of_work", 
                "performance_standards", "reverse_auction", "msme_preferences", 
                "border_country_clause", "rejection_criteria", "documentation_requirements", "additional_details"
            ]
            
            for field in required_fields:
                if field not in overview_data:
                    overview_data[field] = "Not specified in document"
            
            # Apply fallback validation for critical fields
            overview_data = apply_focused_fallback_validation(overview_data, text_content, field_keywords)
            
            # Post-process content to ensure proper formatting
            for field in overview_data:
                if isinstance(overview_data[field], str):
                    overview_data[field] = format_lengthy_content(overview_data[field])
            
            print("[DEBUG] Successfully extracted overview data", flush=True)
            return overview_data
            
        except Exception as e:
            print(f"[ERROR] Error parsing overview: {e}", flush=True)
            print(f"[ERROR] Raw response: {response.text[:1000] if hasattr(response, 'text') and response.text else 'No response text'}", flush=True)
            return create_focused_default_overview("Error extracting data")
            
    except Exception as e:
        print(f"[ERROR] Error generating overview: {e}", flush=True)
        import traceback
        print(f"[ERROR] Traceback: {traceback.format_exc()}", flush=True)
        return create_focused_default_overview("Error in processing")

def robust_json_parse(text_response, fallback_data=None):
    """
    Robust JSON parsing that handles various malformed JSON issues from LLMs
    """
    print(f"[DEBUG] Attempting to parse JSON from response of length: {len(text_response)}", flush=True)
    
    # Strategy 1: Try direct JSON parsing first
    try:
        return json.loads(text_response)
    except json.JSONDecodeError as e:
        print(f"[DEBUG] Direct JSON parse failed: {e}", flush=True)
    
    # Strategy 2: Extract JSON from code blocks
    json_patterns = [
        r'```json\s*(\{.*?\})\s*```',  # JSON in code blocks
        r'```\s*(\{.*?\})\s*```',      # JSON in generic code blocks
        r'(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})',  # Any JSON-like structure
    ]
    
    for pattern in json_patterns:
        matches = re.findall(pattern, text_response, re.DOTALL)
        for match in matches:
            try:
                print(f"[DEBUG] Trying pattern match: {match[:200]}...", flush=True)
                return json.loads(match)
            except json.JSONDecodeError:
                continue
    
    # Strategy 3: Clean common JSON issues and retry
    cleaned_text = text_response
    
    # Remove common prefixes/suffixes
    prefixes_to_remove = [
        "Here's the JSON:",
        "Here is the JSON:",
        "The JSON object is:",
        "```json",
        "```",
    ]
    
    for prefix in prefixes_to_remove:
        if cleaned_text.startswith(prefix):
            cleaned_text = cleaned_text[len(prefix):].strip()
    
    # Remove trailing markdown
    if cleaned_text.endswith("```"):
        cleaned_text = cleaned_text[:-3].strip()
    
    # Fix common JSON issues
    try:
        # Remove trailing commas before closing brackets/braces
        cleaned_text = re.sub(r',(\s*[}\]])', r'\1', cleaned_text)
        
        # Try parsing the cleaned text
        print(f"[DEBUG] Trying cleaned JSON: {cleaned_text[:200]}...", flush=True)
        return json.loads(cleaned_text)
    except json.JSONDecodeError as e:
        print(f"[DEBUG] Cleaned JSON parse failed: {e}", flush=True)
    
    # Strategy 4: Extract individual fields if full JSON parsing fails
    print("[DEBUG] Full JSON parsing failed, attempting field extraction", flush=True)
    
    extracted_data = {}
    
    # Define field patterns to extract individual fields
    field_patterns = {
        'tender_number': r'"tender_number":\s*"([^"]*)"',
        'organization_details': r'"organization_details":\s*"([^"]*)"',
        'due_date': r'"due_date":\s*"([^"]*)"',
         'bid_opening_date': r'"bid_opening_date":\s*"([^"]*)"',
        'bid_offer_validity': r'"bid_offer_validity":\s*"([^"]*)"',
        'question_deadline': r'"question_deadline":\s*"([^"]*)"',
        'emd_amount': r'"emd_amount":\s*"([^"]*)"',
        'estimated_cost': r'"estimated_cost":\s*"([^"]*)"',
        'performance_security': r'"performance_security":\s*"([^"]*)"',
        'payment_terms': r'"payment_terms":\s*"([^"]*)"',
        'qualification_criteria': r'"qualification_criteria":\s*"([^"]*)"',
        'evaluation_criteria': r'"evaluation_criteria":\s*"([^"]*)"',
        'technical_specifications': r'"technical_specifications":\s*"([^"]*)"',
        'scope_of_work': r'"scope_of_work":\s*"([^"]*)"',
        'performance_standards': r'"performance_standards":\s*"([^"]*)"',
        'reverse_auction': r'"reverse_auction":\s*"([^"]*)"',
        'msme_preferences': r'"msme_preferences":\s*"([^"]*)"',
        'border_country_clause': r'"border_country_clause":\s*"([^"]*)"',
        'rejection_criteria': r'"rejection_criteria":\s*"([^"]*)"',
        'documentation_requirements': r'"documentation_requirements":\s*"([^"]*)"'
    }
    
    for field, pattern in field_patterns.items():
        match = re.search(pattern, text_response, re.DOTALL | re.IGNORECASE)
        if match:
            extracted_data[field] = match.group(1)
            print(f"[DEBUG] Extracted {field}: {match.group(1)[:50]}...", flush=True)
        else:
            extracted_data[field] = "Not specified in document"
    
    if extracted_data:
        print(f"[DEBUG] Successfully extracted {len(extracted_data)} fields", flush=True)
        return extracted_data
    
    # Final fallback
    print("[ERROR] All JSON parsing strategies failed", flush=True)
    return fallback_data or create_focused_default_overview("JSON parsing failed")
    
def apply_focused_fallback_validation(overview_data, text_content, field_keywords):
    """Apply fallback validation for selected fields only"""
    text_lower = text_content.lower()
    
    # Fallback for Due Date
    if overview_data.get("due_date") in ["Not specified in document", "", None]:
        date_patterns = [
            r'due date[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'closing date[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'submission[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'last date[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'deadline[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})'
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, text_lower)
            if match:
                # Get surrounding context for more details
                pos = text_lower.find(match.group(0))
                context = text_content[max(0, pos-100):pos+200]
                overview_data["due_date"] = f"Found date reference: {match.group(1)} (Context: {context.strip()})"
                break
    
    # Fallback for Bid Opening Date
    if overview_data.get("bid_opening_date") in ["Not specified in document", "", None]:
        match = re.search(r'(?:bid opening|opening of bids)[:\s]+([\w\s,/-]+)', text_lower)
        if match:
            overview_data["bid_opening_date"] = f"Found: {match.group(1).strip()}"

    # Fallback for Bid Offer Validity
    if overview_data.get("bid_offer_validity") in ["Not specified in document", "", None]:
        match = re.search(r'(?:validity of bid|offer valid for)[:\s]+([\w\s,/-]+)', text_lower)
        if match:
            overview_data["bid_offer_validity"] = f"Found: {match.group(1).strip()}"

    # Fallback for EMD Amount
    if overview_data.get("emd_amount") in ["Not specified in document", "", None]:
        emd_patterns = [
            r'emd[:\s]+(?:rs\.?|inr|₹)?\s*(\d+(?:,\d+)*(?:\.\d+)?)',
            r'earnest money[:\s]+(?:rs\.?|inr|₹)?\s*(\d+(?:,\d+)*(?:\.\d+)?)',
            r'bid security[:\s]+(?:rs\.?|inr|₹)?\s*(\d+(?:,\d+)*(?:\.\d+)?)',
            r'security deposit[:\s]+(?:rs\.?|inr|₹)?\s*(\d+(?:,\d+)*(?:\.\d+)?)'
        ]
        
        for pattern in emd_patterns:
            match = re.search(pattern, text_lower)
            if match:
                # Get surrounding context for conditions and format details
                pos = text_lower.find(match.group(0))
                context = text_content[max(0, pos-150):pos+300]
                overview_data["emd_amount"] = f"Found amount reference: ₹{match.group(1)} (Details: {context.strip()})"
                break
            
    # Fallback for Estimated Cost
    if overview_data.get("estimated_cost") in ["Not specified in document", "", None]:
        match = re.search(r'(?:estimated cost|tender value|approx(?:imate)? value)[:\s]+([₹\w\s,.\d/-]+)', text_lower)
        if match:
            overview_data["estimated_cost"] = f"Found: {match.group(1).strip()}"

    # Fallback for Tender Number
    if overview_data.get("tender_number") in ["Not specified in document", "", None]:
        number_patterns = [
            r'(?:tender\s+no\.?|gem/)\s*:?\s*([A-Z0-9/\-_]+)',
            r'(GEM/\d{4}/[A-Z]/\d+)',
            r'(?:reference\s+no\.?|rfp\s+no\.?)\s*:?\s*([A-Z0-9/\-_]+)',
            r'(?:notice\s+no\.?|nit\s+no\.?)\s*:?\s*([A-Z0-9/\-_]+)'
        ]
        
        for pattern in number_patterns:
            match = re.search(pattern, text_content, re.IGNORECASE)
            if match:
                overview_data["tender_number"] = f"Found: {match.group(1)}"
                break
    
    # Fallback for Organization Details
    if overview_data.get("organization_details") in ["Not specified in document", "", None]:
        org_patterns = [
            r'(?:issued\s+by|tender\s+issuing\s+authority|procuring\s+entity)\s*:?\s*([^.\n]{10,200})',
            r'(?:buyer|purchaser|organization)\s*:?\s*([^.\n]{10,200})',
            r'(?:department|ministry)\s+of\s+([^.\n]{5,150})'
        ]
        
        for pattern in org_patterns:
            match = re.search(pattern, text_content, re.IGNORECASE)
            if match:
                overview_data["organization_details"] = f"Found: {match.group(1).strip()}"
                break
    
    # Fallback for Performance Security
    if overview_data.get("performance_security") in ["Not specified in document", "", None]:
        performance_patterns = [
            r'performance\s+(?:security|guarantee|bond)[:\s]+([^.\n]{10,200})',
            r'contract\s+security[:\s]+([^.\n]{10,200})',
            r'post\s+award\s+security[:\s]+([^.\n]{10,200})'
        ]
        
        for pattern in performance_patterns:
            match = re.search(pattern, text_lower)
            if match:
                pos = text_lower.find(match.group(0))
                context = text_content[pos:pos+300]
                overview_data["performance_security"] = f"Found reference: {context.strip()}"
                break
    
    # Fallback for Reverse Auction
    if overview_data.get("reverse_auction") in ["Not specified in document", "", None]:
        auction_phrases = [
            "reverse auction", "e-auction", "tie at the lowest bid", 
            "tie at l1", "auction as per gem", "bid tie", "dutch auction"
        ]
        
        for phrase in auction_phrases:
            if phrase in text_lower:
                pos = text_lower.find(phrase)
                context = text_content[max(0, pos-100):pos+200]
                overview_data["reverse_auction"] = f"Found reference: '{phrase}' (Context: {context.strip()})"
                break
    
    # Fallback for MSME Preferences
    if overview_data.get("msme_preferences") in ["Not specified in document", "", None]:
        msme_phrases = [
            "msme", "micro small medium", "purchase preference", 
            "price preference", "small scale industry", "startup", "women entrepreneur"
        ]
        
        for phrase in msme_phrases:
            if phrase in text_lower:
                pos = text_lower.find(phrase)
                context = text_content[max(0, pos-150):pos+250]
                overview_data["msme_preferences"] = f"Found MSME reference: {context.strip()}"
                break
    
    # Fallback for Border Country Clause
    if overview_data.get("border_country_clause") in ["Not specified in document", "", None]:
        border_phrases = [
            "sharing land border", "china", "pakistan", "security clearance",
            "prior security clearance", "competent authority", "banned countries"
        ]
        
        for phrase in border_phrases:
            if phrase in text_lower:
                pos = text_lower.find(phrase)
                context = text_content[max(0, pos-200):pos+300]
                overview_data["border_country_clause"] = f"Found border clause reference: {context.strip()}"
                break
    
    return overview_data

def format_lengthy_content(content):
    """Enhanced formatting for lengthy content with better structure and bullet points"""
    if not content or content in ["Not specified in document", "Not specified"]:
        return content
    
    # Handle escaped newlines and formatting from AI response
    content = content.replace('\\n', '\n')
    content = content.replace('\\•', '•')
    
    # If content is already well-formatted (has bullets or structure), return as-is
    if '•' in content or '**' in content:
        return content
    
    # For plain text longer than 300 characters, try to create structure
    if len(content) > 300 and '\n' not in content:
        # Try to split by common separators and create bullet points
        separators = [';', '|', ' and ', ' & ', '. ', ',']
        best_split = None
        best_count = 0
        
        for sep in separators:
            parts = content.split(sep)
            if len(parts) > best_count and len(parts) <= 8:  # Don't over-split
                valid_parts = [p.strip() for p in parts if len(p.strip()) > 15]
                if len(valid_parts) >= 2:
                    best_split = valid_parts
                    best_count = len(valid_parts)
        
        if best_split and len(best_split) >= 2:
            formatted_parts = []
            for part in best_split:
                part = part.strip()
                if part:
                    # Ensure proper punctuation
                    if not part.endswith('.') and not part.endswith(':') and len(part) > 20:
                        part += '.'
                    formatted_parts.append(f"• {part}")
            
            if formatted_parts:
                return '\n'.join(formatted_parts)
    
    return content

def extract_prioritized_sections(text_content, field_keywords):
    """Extract and prioritize document sections based on field keywords"""
    text_lower = text_content.lower()
    prioritized_sections = []
    found_positions = set()
    
    # Score each section based on keyword density and importance
    for field, keywords in field_keywords.items():
        field_sections = []
        for keyword in keywords:
            start_pos = 0
            while True:
                pos = text_lower.find(keyword.lower(), start_pos)
                if pos == -1:
                    break
                
                # Avoid overlapping sections
                if not any(abs(pos - found_pos) < 300 for found_pos in found_positions):
                    context_start = max(0, pos - 800)  # Larger context window
                    context_end = min(len(text_content), pos + 800)
                    context = text_content[context_start:context_end]
                    
                    # Calculate relevance score
                    relevance_score = calculate_section_relevance(context, keywords)
                    
                    field_sections.append({
                        'text': f"\n--- SECTION: {field.upper().replace('_', ' ')} (keyword: '{keyword}', score: {relevance_score:.2f}) ---\n{context}\n",
                        'position': pos,
                        'field': field,
                        'score': relevance_score
                    })
                    found_positions.add(pos)
                
                start_pos = pos + 1
        
        # Sort by relevance score and take top sections per field
        field_sections.sort(key=lambda x: x['score'], reverse=True)
        prioritized_sections.extend(field_sections[:3])  # Top 3 per field
    
    # Sort all sections by score
    prioritized_sections.sort(key=lambda x: x['score'], reverse=True)
    
    return [section['text'] for section in prioritized_sections]

def calculate_section_relevance(text, keywords):
    """Calculate relevance score for a text section based on keyword presence"""
    text_lower = text.lower()
    score = 0
    
    for keyword in keywords:
        # Count occurrences
        count = text_lower.count(keyword.lower())
        # Weight by keyword length (longer keywords are more specific)
        weight = len(keyword.split())
        score += count * weight
    
    # Normalize by text length
    return score / (len(text) / 1000)
    
def create_focused_default_overview(status):
    """Helper function to create default overview data for selected fields only"""
    return {
        "tender_number": status,
        "organization_details": status,
        "due_date": status,
        "bid_opening_date": status,
        "bid_offer_validity": status,
        "question_deadline": status,
        "emd_amount": status,
        "estimated_cost": status,
        "performance_security": status,
        "payment_terms": status,
        "qualification_criteria": status,
        "evaluation_criteria": status,
        "technical_specifications": status,
        "scope_of_work": status,
        "performance_standards": status,
        "reverse_auction": status,
        "msme_preferences": status,
        "border_country_clause": status,
        "rejection_criteria": status,
        "documentation_requirements": status
    }

# def create_new_tender(user_id, organization_id, files):  
#     """Create a new tender with uploaded files and extract proper title"""    
    
#     # Default fallback
#     tender_title = f"Tender {uuid.uuid4().hex[:8]}"
    
#     # Extract title first to check for existing tender
#     extracted_tender_number = None
#     if files:
#         first_file = files[0]
#         file_extension = os.path.splitext(first_file.filename)[1].lower()
        
#         if file_extension in ['.pdf', '.txt']:
#             try:
#                 # Save temporarily for extraction
#                 unique_filename = secure_filename(f"{uuid.uuid4()}_{first_file.filename}")
#                 temp_file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
#                 first_file.save(temp_file_path)

#                 # Extract preview text
#                 temp_content = ""
#                 if file_extension == '.pdf':
#                     with fitz.open(temp_file_path) as doc:
#                         for i, page in enumerate(doc):
#                             if i >= 2:   # only first 2 pages for speed
#                                 break
#                             temp_content += page.get_text() or ""
#                 else:  # .txt
#                     with open(temp_file_path, 'r', encoding='utf-8') as f:
#                         temp_content = f.read()
                
#                 first_file.seek(0)  # reset pointer for later
                
#                 # Use Gemini to extract title
#                 if temp_content.strip():
#                     model = init_gemini()
#                     preview = temp_content[:2000]
#                     prompt = f"""
#                     Extract tender number and title from this document. Return only JSON like:
#                     {{"number": "GEM/2023/B/3292506", "title": "Procurement of Ball Valves on ARC Basis"}}
                    
#                     Text: {preview}
#                     """
#                     response = model.generate_content(prompt)

#                     try:
#                         json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
#                         if json_match:
#                             result = json.loads(json_match.group(0))
#                             number = result.get('number', f"TDR-{datetime.datetime.now().year}-001")
#                             title = result.get('title', "Tender Document")
#                             tender_title = f"{number} - {title}"
#                             extracted_tender_number = number  # Store for duplicate check
#                             print(f"[INFO] Extracted title: {tender_title}")
#                         else:
#                             print("[WARN] No JSON found in Gemini response")
#                     except Exception as e:
#                         print(f"[WARN] Failed to parse title JSON: {e}")
                
#                 os.remove(temp_file_path)

#             except Exception as e:
#                 print(f"[WARN] Title extraction failed: {e}")
#                 first_file.seek(0)  # ensure file is reusable
    
#     # ========== CHECK FOR EXISTING TENDER ==========
#     existing_tender = None
#     new_source = 'External_Analyze'  # Default source for uploaded tenders
    
#     if extracted_tender_number:
#         # Check for CPPP_Original tenders in tender_reference_number
#         existing_tender = Tender.query.filter_by(
#             tender_reference_number=extracted_tender_number,
#             source='CPPP_Original'
#         ).first()
        
#         if existing_tender:
#             print(f"[INFO] Found existing CPPP_Original tender in tender_reference_number: {extracted_tender_number}")
#             new_source = 'CPPP_Analyze'
#         else:
#             # Check for MahaTender_Original tenders in tender_number
#             existing_tender = Tender.query.filter_by(
#                 tender_number=extracted_tender_number,
#                 source='MahaTender_Original'
#             ).first()
            
#             if existing_tender:
#                 print(f"[INFO] Found existing MahaTender_Original tender in tender_number: {extracted_tender_number}")
#                 new_source = 'MahaTender_Analyze'
#             else:
#                 # Check for GEM_Original tenders in tender_number
#                 existing_tender = Tender.query.filter_by(
#                     tender_number=extracted_tender_number,
#                     source='GEM_Original'
#                 ).first()
                
#                 if existing_tender:
#                     print(f"[INFO] Found existing GEM_Original tender in tender_number: {extracted_tender_number}")
#                     new_source = 'GEM_Analyze'
    
#     # ========== CREATE OR UPDATE TENDER ==========
#     if existing_tender:
#         # UPDATE EXISTING TENDER
#         print(f"[INFO] Updating existing tender ID: {existing_tender.id}")
#         existing_tender.title = tender_title
#         existing_tender.user_id = user_id
#         existing_tender.organization_id = organization_id
#         existing_tender.source = new_source
#         existing_tender.updated_at = datetime.datetime.now()
        
#         # Use the existing tender as new_tender
#         new_tender = existing_tender
        
#     else:
#         # CREATE NEW TENDER
#         print(f"[INFO] Creating new tender")
#         new_tender = Tender(
#             title=tender_title,
#             user_id=user_id,
#             organization_id=organization_id,
#             source=new_source  # Add source to new tender
#         )
#         db.session.add(new_tender)
#         db.session.flush()  # Get ID before commit
    
#     # Process uploaded files
#     processed_files, errors = [], []
#     main_document_content = None
#     all_documents_content = []  # New: collect all content
#     processed_documents = []  # Store document objects for hyperlink extraction
    
#     for index, file in enumerate(files):
#         file_extension = os.path.splitext(file.filename)[1].lower()
#         if file_extension not in ['.pdf', '.txt']:
#             errors.append(f"{file.filename}: Only PDF and TXT files are supported")
#             continue

#         try:
#             file_data = save_uploaded_file(file)
#             is_primary = (index == 0)
            
#             document = Document(
#                 filename=file_data['filename'],
#                 original_filename=file_data['original_filename'],
#                 file_path=file_data['file_path'],
#                 file_type=file_data['file_type'],
#                 file_size=file_data['file_size'],
#                 # content_text=file_data['content_text'],
#                 is_primary=is_primary,
#                 tender_id=new_tender.id
#             )
#             db.session.add(document)
#             processed_documents.append(document)  # Store for hyperlink extraction

#             if is_primary:
#                 main_document_content = file_data['content_text']
            
#             # Collect all document content but limit each to prevent overflow
#             if file_data['content_text']:
#                 # Limit each document to 150k characters to prevent processing issues
#                 limited_content = file_data['content_text'][:150000]
#                 all_documents_content.append({
#                     'content': limited_content,
#                     'filename': file.filename,
#                     'is_primary': is_primary
#                 })
            
#             processed_files.append(file.filename)
        
#         except Exception as e:
#             errors.append(f"{file.filename}: {str(e)}")

#     # Extract overview with intelligent content combination AND hyperlink support
#     if all_documents_content:
#         try:
#             if len(all_documents_content) == 1:
#                 # Single document - use as is
#                 content_for_overview = all_documents_content[0]['content']
#                 print(f"[INFO] Single document processing: {len(content_for_overview):,} characters")
#             else:
#                 # Multiple documents - smart combination strategy
#                 print(f"[INFO] Processing {len(all_documents_content)} documents")
                
#                 # Start with primary document
#                 primary_doc = next((doc for doc in all_documents_content if doc['is_primary']), all_documents_content[0])
#                 content_for_overview = primary_doc['content']
                
#                 # Add sections from other documents
#                 for doc in all_documents_content:
#                     if not doc['is_primary']:
#                         # Add a separator and portion of additional documents
#                         additional_content = f"\n\n--- ADDITIONAL DOCUMENT: {doc['filename']} ---\n"
#                         additional_content += doc['content'][:50000]  # Limit additional docs to 80k chars
#                         content_for_overview += additional_content
                
#                 # Final safety check on total content length
#                 if len(content_for_overview) > 400000:
#                     print(f"[WARN] Combined content very large ({len(content_for_overview):,} chars), truncating")
#                     content_for_overview = content_for_overview[:400000]
#                     # Try to end at a sentence boundary
#                     last_period = content_for_overview.rfind('.')
#                     if last_period > 300000:
#                         content_for_overview = content_for_overview[:last_period + 1]
                
#                 print(f"[INFO] Combined content length: {len(content_for_overview):,} characters")
            
#             # Get the primary document path for hyperlink extraction
#             primary_doc_path = None
#             primary_doc = next((doc for doc in processed_documents if doc.is_primary), None)
#             if primary_doc and primary_doc.file_path and os.path.exists(primary_doc.file_path):
#                 primary_doc_path = primary_doc.file_path
#                 print(f"[INFO] Using primary document for hyperlink extraction: {primary_doc_path}")
            
#             # Extract overview data WITH HYPERLINK SUPPORT
#             overview_data = extract_tender_overview(content_for_overview, primary_doc_path)
            
#             # Apply overview data to tender record
#             new_tender.due_date = overview_data.get('due_date')
#             new_tender.bid_opening_date = overview_data.get('bid_opening_date')
#             new_tender.bid_offer_validity = overview_data.get('bid_offer_validity')
#             new_tender.emd_amount = overview_data.get('emd_amount')
#             new_tender.qualification_criteria = overview_data.get('qualification_criteria')
#             new_tender.question_deadline = overview_data.get('question_deadline')
#             new_tender.reverse_auction = overview_data.get('reverse_auction')
#             new_tender.rejection_criteria = overview_data.get('rejection_criteria')
#             new_tender.msme_preferences = overview_data.get('msme_preferences')
#             new_tender.border_country_clause = overview_data.get('border_country_clause')
#             new_tender.tender_number = overview_data.get('tender_number') or extracted_tender_number
#             new_tender.organization_details = overview_data.get('organization_details')
#             new_tender.performance_security = overview_data.get('performance_security')
#             new_tender.payment_terms = overview_data.get('payment_terms')
#             new_tender.technical_specifications = overview_data.get('technical_specifications')
#             new_tender.scope_of_work = overview_data.get('scope_of_work')
#             new_tender.performance_standards = overview_data.get('performance_standards')
#             new_tender.evaluation_criteria = overview_data.get('evaluation_criteria')
#             new_tender.documentation_requirements = overview_data.get('documentation_requirements')
#             new_tender.additional_details = overview_data.get('additional_details')
            
#             print(f"[INFO] Overview extraction completed successfully")

#             # --- Insert Products (if available) for uploaded tender ---
#             try:
#                 products_data = overview_data.get('products_table') or []
#                 if isinstance(products_data, list) and len(products_data) > 0:
#                     print(f"[DEBUG] Inserting {len(products_data)} products for Tender ID={new_tender.id}")
#                     for p in products_data:
#                         product = Product(
#                             tender_id=new_tender.id,
#                             product_name=p.get('product_name', 'Not specified'),
#                             quantity=p.get('quantity', 'Not specified'),
#                             delivery_days=p.get('delivery_days', 'Not specified'),
#                             consignee_name=p.get('consignee_name', 'Not specified'),
#                             delivery_address=p.get('delivery_address', 'Not specified'),
#                             specification_link=p.get('specification_link') or None
#                         )
#                         db.session.add(product)
#                     print(f"[DEBUG] Products queued for insert for Tender ID={new_tender.id}")
#                 else:
#                     print("[INFO] No product data found in overview_data for uploaded tender.")
#             except Exception as e:
#                 print(f"[ERROR] Failed to insert products for uploaded tender: {e}")
#                 import traceback
#                 print(traceback.format_exc())
#                 # Continue — we still want to commit other data

#         except Exception as e:
#             print(f"[ERROR] Overview extraction failed: {e}")
#             import traceback
#             traceback.print_exc()
#             # Continue without overview data rather than failing the entire upload
#             print("[WARN] Continuing without overview data")
    
#     if processed_files:
#         db.session.commit()
#         return {
#             'success': True,
#             'tender_id': new_tender.id,
#             'tender_action': 'updated' if existing_tender else 'created',
#             'source': new_tender.source,
#             'processed_files': processed_files,
#             'errors': errors
#         }
#     else:
#         db.session.rollback()
#         return {
#             'success': False,
#             'errors': errors or ['No files were processed successfully']
#         }

# def create_new_tender(user_id, organization_id, files):  
#     """Create a new tender with uploaded files and extract proper title"""    
    
#     # Default fallback
#     tender_title = f"Tender {uuid.uuid4().hex[:8]}"
    
#     # Extract title first to check for existing tender
#     extracted_tender_number = None
#     if files:
#         first_file = files[0]
#         file_extension = os.path.splitext(first_file.filename)[1].lower()
        
#         if file_extension in ['.pdf', '.txt']:
#             try:
#                 # Save temporarily for extraction
#                 unique_filename = secure_filename(f"{uuid.uuid4()}_{first_file.filename}")
#                 temp_file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
#                 first_file.save(temp_file_path)

#                 # Extract preview text
#                 temp_content = ""
#                 if file_extension == '.pdf':
#                     with fitz.open(temp_file_path) as doc:
#                         for i, page in enumerate(doc):
#                             if i >= 2:   # only first 2 pages for speed
#                                 break
#                             temp_content += page.get_text() or ""
#                 else:  # .txt
#                     with open(temp_file_path, 'r', encoding='utf-8') as f:
#                         temp_content = f.read()
                
#                 first_file.seek(0)  # reset pointer for later
                
#                 # Use Gemini to extract title
#                 if temp_content.strip():
#                     model = init_gemini()
#                     preview = temp_content[:2000]
#                     prompt = f"""
#                     Extract tender number and title from this document. Return only JSON like:
#                     {{"number": "GEM/2023/B/3292506", "title": "Procurement of Ball Valves on ARC Basis"}}
                    
#                     Text: {preview}    
#                     """
#                     response = model.generate_content(prompt)

#                     try:
#                         json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
#                         if json_match:
#                             result = json.loads(json_match.group(0))
#                             number = result.get('number', f"TDR-{datetime.datetime.now().year}-001")
#                             title = result.get('title', "Tender Document")
#                             tender_title = f"{number} - {title}"
#                             extracted_tender_number = number  # Store for duplicate check
#                             print(f"[INFO] Extracted tender number: {extracted_tender_number}")
#                         else:
#                             print("[WARN] No JSON found in Gemini response")
#                     except Exception as e:
#                         print(f"[WARN] Failed to parse title JSON: {e}")
                
#                 os.remove(temp_file_path)

#             except Exception as e:
#                 print(f"[WARN] Title extraction failed: {e}")
#                 first_file.seek(0)  # ensure file is reusable
    
#     # ========== CHECK FOR EXISTING TENDER ==========
#     # existing_tender = None
#     # new_source = 'External_Analyze'  # Default source for uploaded tenders
    
#     # if extracted_tender_number:
#     #     # Check for CPPP_Original tenders in tender_reference_number
#     #     existing_tender = Tender.query.filter_by(
#     #         tender_reference_number=extracted_tender_number,
#     #         source='CPPP_Original'
#     #     ).first()
        
#     #     if existing_tender:
#     #         print(f"[INFO] Found existing CPPP_Original tender in tender_reference_number: {extracted_tender_number}")
#     #         new_source = 'CPPP_Analyze'
#     #     else:
#     #         # Check for MahaTender_Original tenders in tender_reference_number
#     #         existing_tender = Tender.query.filter_by(
#     #             tender_reference_number=extracted_tender_number,
#     #             source='MahaTender_Original'
#     #         ).first()
            
#     #         if existing_tender:
#     #             print(f"[INFO] Found existing MahaTender_Original tender in tender_reference_number: {extracted_tender_number}")
#     #             new_source = 'MahaTender_Analyze'
#     #         else:
#     #             # Check for GEM_Original tenders in tender_number
#     #             existing_tender = Tender.query.filter_by(
#     #                 tender_number=extracted_tender_number,
#     #                 source='GEM_Original'
#     #             ).first()
                
#     #             if existing_tender:
#     #                 print(f"[INFO] Found existing GEM_Original tender in tender_number: {extracted_tender_number}")
#     #                 new_source = 'GEM_Analyze'


#     existing_tender = None
#     new_source = 'External_Analyze'

#     if extracted_tender_number:
#         extracted_upper = extracted_tender_number.upper().replace(' ', '')

#         # Check for CPPP_Original tenders
#         tenders = Tender.query.filter_by(source='CPPP_Original').all()
#         for tender in tenders:
#             if (tender.tender_reference_number and tender.tender_reference_number.upper().replace(' ', '') in extracted_upper):
#                 print(f"[INFO] Found existing CPPP_Original tender in tender_reference_number: {tender.tender_reference_number}")
#                 existing_tender = tender
#                 new_source = 'CPPP_Analyze'
#                 break

#         if not existing_tender:
#             # Check for MahaTender_Original tenders
#             tenders = Tender.query.filter_by(source='MahaTender_Original').all()
#             for tender in tenders:
#                 if tender.tender_reference_number and tender.tender_reference_number.upper().replace(' ', '') in extracted_upper:
#                     print(f"[INFO] Found existing MahaTender_Original tender in tender_reference_number: {tender.tender_reference_number}")
#                     existing_tender = tender
#                     new_source = 'MahaTender_Analyze'
#                     break

#         if not existing_tender:
#             # Check for GEM_Original tenders
#             tenders = Tender.query.filter_by(source='GEM_Original').all()
#             for tender in tenders:
#                 if tender.tender_number and tender.tender_number.upper().replace(' ', '') in extracted_upper:
#                     print(f"[INFO] Found existing GEM_Original tender in tender_number: {tender.tender_number}")
#                     existing_tender = tender
#                     new_source = 'GEM_Analyze'
#                     break

#     # ========== CREATE OR UPDATE TENDER ==========
#     if existing_tender:
#         # UPDATE EXISTING TENDER
#         print(f"[INFO] Updating existing tender ID: {existing_tender.id}")
#         existing_tender.title = tender_title
#         existing_tender.user_id = user_id
#         existing_tender.organization_id = organization_id
#         existing_tender.source = new_source
#         existing_tender.updated_at = datetime.datetime.now()
        
#         # Use the existing tender as new_tender
#         new_tender = existing_tender
        
#     else:
#         # CREATE NEW TENDER - Store extracted number in appropriate column
#         print(f"[INFO] Creating new tender")
#         new_tender = Tender(
#             title=tender_title,
#             user_id=user_id,
#             organization_id=organization_id,
#             source=new_source  # Add source to new tender
#         )
        
#         # Store extracted tender number in appropriate column based on source
#         if extracted_tender_number:
#             if new_source in ['CPPP_Analyze', 'MahaTender_Analyze']:
#                 # For CPPP and MahaTender sources, store in tender_reference_number
#                 new_tender.tender_reference_number = extracted_tender_number
#                 print(f"[INFO] Storing {extracted_tender_number} in tender_reference_number for source {new_source}")
#             elif new_source == 'GEM_Analyze':
#                 # For GEM source, store in tender_number
#                 new_tender.tender_number = extracted_tender_number
#                 print(f"[INFO] Storing {extracted_tender_number} in tender_number for source {new_source}")
#             else:
#                 # For External_Analyze or other sources, store in both for consistency
#                 new_tender.tender_number = extracted_tender_number
#                 print(f"[INFO] Storing {extracted_tender_number} in tender_number for source {new_source}")
        
#         db.session.add(new_tender)
#         db.session.flush()  # Get ID before commit
    
#     # Process uploaded files
#     processed_files, errors = [], []
#     main_document_content = None
#     all_documents_content = []  # New: collect all content
#     processed_documents = []  # Store document objects for hyperlink extraction
    
#     for index, file in enumerate(files):
#         file_extension = os.path.splitext(file.filename)[1].lower()
#         if file_extension not in ['.pdf', '.txt']:
#             errors.append(f"{file.filename}: Only PDF and TXT files are supported")
#             continue

#         try:
#             file_data = save_uploaded_file(file)
#             is_primary = (index == 0)
            
#             document = Document(
#                 filename=file_data['filename'],
#                 original_filename=file_data['original_filename'],
#                 file_path=file_data['file_path'],
#                 file_type=file_data['file_type'],
#                 file_size=file_data['file_size'],
#                 is_primary=is_primary,
#                 tender_id=new_tender.id
#             )
#             db.session.add(document)
#             processed_documents.append(document)  # Store for hyperlink extraction

#             if is_primary:
#                 main_document_content = file_data['content_text']
            
#             # Collect all document content but limit each to prevent overflow
#             if file_data['content_text']:
#                 # Limit each document to 150k characters to prevent processing issues
#                 limited_content = file_data['content_text'][:150000]
#                 all_documents_content.append({
#                     'content': limited_content,
#                     'filename': file.filename,
#                     'is_primary': is_primary
#                 })
            
#             processed_files.append(file.filename)
        
#         except Exception as e:
#             errors.append(f"{file.filename}: {str(e)}")

#     # Extract overview with intelligent content combination AND hyperlink support
#     if all_documents_content:
#         try:
#             if len(all_documents_content) == 1:
#                 # Single document - use as is
#                 content_for_overview = all_documents_content[0]['content']
#                 print(f"[INFO] Single document processing: {len(content_for_overview):,} characters")
#             else:
#                 # Multiple documents - smart combination strategy
#                 print(f"[INFO] Processing {len(all_documents_content)} documents")
                
#                 # Start with primary document
#                 primary_doc = next((doc for doc in all_documents_content if doc['is_primary']), all_documents_content[0])
#                 content_for_overview = primary_doc['content']
                
#                 # Add sections from other documents
#                 for doc in all_documents_content:
#                     if not doc['is_primary']:
#                         # Add a separator and portion of additional documents
#                         additional_content = f"\n\n--- ADDITIONAL DOCUMENT: {doc['filename']} ---\n"
#                         additional_content += doc['content'][:50000]  # Limit additional docs to 80k chars
#                         content_for_overview += additional_content
                
#                 # Final safety check on total content length
#                 if len(content_for_overview) > 400000:
#                     print(f"[WARN] Combined content very large ({len(content_for_overview):,} chars), truncating")
#                     content_for_overview = content_for_overview[:400000]
#                     # Try to end at a sentence boundary
#                     last_period = content_for_overview.rfind('.')
#                     if last_period > 300000:
#                         content_for_overview = content_for_overview[:last_period + 1]
                
#                 print(f"[INFO] Combined content length: {len(content_for_overview):,} characters")
            
#             # Get the primary document path for hyperlink extraction
#             primary_doc_path = None
#             primary_doc = next((doc for doc in processed_documents if doc.is_primary), None)
#             if primary_doc and primary_doc.file_path and os.path.exists(primary_doc.file_path):
#                 primary_doc_path = primary_doc.file_path
#                 print(f"[INFO] Using primary document for hyperlink extraction: {primary_doc_path}")
            
#             # Extract overview data WITH HYPERLINK SUPPORT
#             overview_data = extract_tender_overview(content_for_overview, primary_doc_path)
            
#             # Apply overview data to tender record
#             new_tender.due_date = overview_data.get('due_date')
#             new_tender.bid_opening_date = overview_data.get('bid_opening_date')
#             new_tender.bid_offer_validity = overview_data.get('bid_offer_validity')
#             new_tender.emd_amount = overview_data.get('emd_amount')
#             new_tender.qualification_criteria = overview_data.get('qualification_criteria')
#             new_tender.question_deadline = overview_data.get('question_deadline')
#             new_tender.reverse_auction = overview_data.get('reverse_auction')
#             new_tender.rejection_criteria = overview_data.get('rejection_criteria')
#             new_tender.msme_preferences = overview_data.get('msme_preferences')
#             new_tender.border_country_clause = overview_data.get('border_country_clause')
            
#             # IMPORTANT: Only set tender_number from overview if not already set
#             if not new_tender.tender_number:
#                 new_tender.tender_number = overview_data.get('tender_number')
            
#             new_tender.organization_details = overview_data.get('organization_details')
#             new_tender.performance_security = overview_data.get('performance_security')
#             new_tender.payment_terms = overview_data.get('payment_terms')
#             new_tender.technical_specifications = overview_data.get('technical_specifications')
#             new_tender.scope_of_work = overview_data.get('scope_of_work')
#             new_tender.performance_standards = overview_data.get('performance_standards')
#             new_tender.evaluation_criteria = overview_data.get('evaluation_criteria')
#             new_tender.documentation_requirements = overview_data.get('documentation_requirements')
#             new_tender.additional_details = overview_data.get('additional_details')
            
#             print(f"[INFO] Overview extraction completed successfully")

#             # --- Insert Products (if available) for uploaded tender ---
#             try:
#                 products_data = overview_data.get('products_table') or []
#                 if isinstance(products_data, list) and len(products_data) > 0:
#                     print(f"[DEBUG] Inserting {len(products_data)} products for Tender ID={new_tender.id}")
#                     for p in products_data:
#                         product = Product(
#                             tender_id=new_tender.id,
#                             product_name=p.get('product_name', 'Not specified'),
#                             quantity=p.get('quantity', 'Not specified'),
#                             delivery_days=p.get('delivery_days', 'Not specified'),
#                             consignee_name=p.get('consignee_name', 'Not specified'),
#                             delivery_address=p.get('delivery_address', 'Not specified'),
#                             specification_link=p.get('specification_link') or None
#                         )
#                         db.session.add(product)
#                     print(f"[DEBUG] Products queued for insert for Tender ID={new_tender.id}")
#                 else:
#                     print("[INFO] No product data found in overview_data for uploaded tender.")
#             except Exception as e:
#                 print(f"[ERROR] Failed to insert products for uploaded tender: {e}")
#                 import traceback
#                 print(traceback.format_exc())
#                 # Continue — we still want to commit other data

#         except Exception as e:
#             print(f"[ERROR] Overview extraction failed: {e}")
#             import traceback
#             traceback.print_exc()
#             # Continue without overview data rather than failing the entire upload
#             print("[WARN] Continuing without overview data")
    
#     if processed_files:
#         db.session.commit()
#         return {
#             'success': True,
#             'tender_id': new_tender.id,
#             'tender_action': 'updated' if existing_tender else 'created',
#             'source': new_tender.source,
#             'processed_files': processed_files,
#             'errors': errors
#         }
#     else:
#         db.session.rollback()
#         return {
#             'success': False,
#             'errors': errors or ['No files were processed successfully']
#         }

def create_new_tender(user_id, organization_id, files):  
    """Create a new tender with uploaded files and extract proper title"""    
    
    # Default fallback
    tender_title = f"Tender {uuid.uuid4().hex[:8]}"
    
    # Extract title first to check for existing tender
    extracted_tender_number = None
    if files:
        first_file = files[0]
        file_extension = os.path.splitext(first_file.filename)[1].lower()
        
        if file_extension in ['.pdf', '.txt']:
            try:
                # Save temporarily for extraction
                unique_filename = secure_filename(f"{uuid.uuid4()}_{first_file.filename}")
                temp_file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
                first_file.save(temp_file_path)

                # Extract preview text
                temp_content = ""
                if file_extension == '.pdf':
                    with fitz.open(temp_file_path) as doc:
                        for i, page in enumerate(doc):
                            if i >= 2:   # only first 2 pages for speed
                                break
                            temp_content += page.get_text() or ""
                else:  # .txt
                    with open(temp_file_path, 'r', encoding='utf-8') as f:
                        temp_content = f.read()
                
                first_file.seek(0)  # reset pointer for later
                
                # Use Gemini to extract title
                if temp_content.strip():
                    model = init_gemini()
                    preview = temp_content[:2000]
                    prompt = f"""
                    Extract tender number and title from this document. Return only JSON like:
                    {{"number": "GEM/2023/B/3292506", "title": "Procurement of Ball Valves on ARC Basis"}}
                    
                    Text: {preview}    
                    """
                    response = model.generate_content(prompt)

                    try:
                        json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
                        if json_match:
                            result = json.loads(json_match.group(0))
                            number = result.get('number', f"TDR-{datetime.datetime.now().year}-001")
                            title = result.get('title', "Tender Document")
                            tender_title = f"{number} - {title}"
                            extracted_tender_number = number  # Store for duplicate check
                            print(f"[INFO] Extracted tender number: {extracted_tender_number}")
                        else:
                            print("[WARN] No JSON found in Gemini response")
                    except Exception as e:
                        print(f"[WARN] Failed to parse title JSON: {e}")
                
                os.remove(temp_file_path)

            except Exception as e:
                print(f"[WARN] Title extraction failed: {e}")
                first_file.seek(0)  # ensure file is reusable
    
    # ========== CHECK FOR EXISTING TENDER ==========
    existing_tender = None
    new_source = 'External_Analyze'  # Default source for uploaded tenders

    if extracted_tender_number:
        # Normalize the extracted tender number for comparison by removing spaces and converting to uppercase
        # This ensures case-insensitive and whitespace-insensitive matching
        extracted_upper = extracted_tender_number.upper().replace(' ', '')

        # CRITICAL: Different platforms store tender numbers in different database columns
        # We need to check each source type separately with the appropriate column comparison

        '''1. FIRST CHECK: CPPP_Original tenders
         Why: CPPP platform stores tender numbers in the 'tender_reference_number' column
         We need to fetch ALL CPPP_Original tenders because we're doing a substring match
         We use 'in' operator because the extracted number might be a substring of the stored number
         Example: Extracted "GEM/2023/B/3292506" might match "CPPP-GEM/2023/B/3292506-001" in database'''
        tenders = Tender.query.filter_by(source='CPPP_Original').all()
        for tender in tenders:
            # Check if the stored tender_reference_number contains the extracted number
            # We normalize both strings for consistent comparison
            if (tender.tender_reference_number and 
                tender.tender_reference_number.upper().replace(' ', '') in extracted_upper):
                print(f"[INFO] Found existing CPPP_Original tender in tender_reference_number: {tender.tender_reference_number}")
                existing_tender = tender
                # Why update source to 'CPPP_Analyze': This indicates this is an uploaded/analyzed version
                # of an originally CPPP-sourced tender, allowing system to track document lifecycle
                new_source = 'CPPP_Analyze'
                break

        '''2. SECOND CHECK: MahaTender_Original tenders (only if no CPPP match found)
        Why: MahaTender platform also uses 'tender_reference_number' column for tender numbers
        Similar logic to CPPP but for a different source system'''
        if not existing_tender:
            tenders = Tender.query.filter_by(source='MahaTender_Original').all()
            for tender in tenders:
                if tender.tender_reference_number and tender.tender_reference_number.upper().replace(' ', '') in extracted_upper:
                    print(f"[INFO] Found existing MahaTender_Original tender in tender_reference_number: {tender.tender_reference_number}")
                    existing_tender = tender
                    # Why update source to 'MahaTender_Analyze': Marks this as analyzed version of MahaTender document
                    new_source = 'MahaTender_Analyze'
                    break

        '''3. THIRD CHECK: GEM_Original tenders (only if no previous matches found)
        IMPORTANT DIFFERENCE: GEM platform stores tender numbers in 'tender_number' column, not 'tender_reference_number'
        Why: Different database schema design for GEM vs CPPP/MahaTender platforms
        This reflects how different tender platforms structure their data differently'''
        if not existing_tender:
            tenders = Tender.query.filter_by(source='GEM_Original').all()
            for tender in tenders:
                # GEM uses tender_number column, so we check that instead of tender_reference_number
                if tender.tender_number and tender.tender_number.upper().replace(' ', '') in extracted_upper:
                    print(f"[INFO] Found existing GEM_Original tender in tender_number: {tender.tender_number}")
                    existing_tender = tender
                    # Why update source to 'GEM_Analyze': Marks this as analyzed version of GEM document
                    new_source = 'GEM_Analyze'
                    break

    # ========== CREATE OR UPDATE TENDER ==========
    if existing_tender:
        '''UPDATE EXISTING TENDER
        Why update existing tender: When user uploads a document that matches an existing tender,
        we update the existing record rather than creating a duplicate. This maintains data integrity
        and allows analysis of different versions of the same tender document.'''
        print(f"[INFO] Updating existing tender ID: {existing_tender.id}")
        existing_tender.title = tender_title
        existing_tender.user_id = user_id
        existing_tender.organization_id = organization_id
        
        '''CRITICAL: Update the source field to indicate this is now an analyzed version
        Why change source from '_Original' to '_Analyze': 
        1. Tracks that this tender now has uploaded/analyzed documents attached
        2. Differentiates between original platform data and user-uploaded analyzed versions
        3. Allows filtering/searching for tenders with analyzed documents vs. original platform data'''
        existing_tender.source = new_source
        existing_tender.updated_at = datetime.datetime.now()
        
        # Use the existing tender as new_tender
        new_tender = existing_tender
        
    else:
        '''CREATE NEW TENDER - Store extracted number in appropriate column
        Why create new tender: No existing tender matched the extracted number, so this is
        either a completely new tender or from a source system not previously tracked'''
        print(f"[INFO] Creating new tender")
        new_tender = Tender(
            title=tender_title,
            user_id=user_id,
            organization_id=organization_id,
            # Why set source here: Even new tenders need a source designation for consistency
            # 'External_Analyze' indicates this is an uploaded document from an external/unclassified source
            source=new_source
        )
        
        '''Store extracted tender number in appropriate column based on source
        IMPORTANT: Different sources store tender numbers in different database columns
        This ensures data consistency with how each platform's data is structured'''
        if extracted_tender_number:
            if new_source in ['CPPP_Analyze', 'MahaTender_Analyze']:
                '''For CPPP and MahaTender sources, store in tender_reference_number
                Why: These platforms historically use tender_reference_number column
                Maintaining this consistency ensures compatibility with existing queries/reports'''
                new_tender.tender_reference_number = extracted_tender_number
                print(f"[INFO] Storing {extracted_tender_number} in tender_reference_number for source {new_source}")
            elif new_source == 'GEM_Analyze':
                '''For GEM source, store in tender_number
                Why: GEM platform uses tender_number column specifically
                Following the same schema as GEM_Original records'''
                new_tender.tender_number = extracted_tender_number
                print(f"[INFO] Storing {extracted_tender_number} in tender_number for source {new_source}")
            else:
                '''For External_Analyze or other sources, store in both for consistency
                Why store in both: External sources don't have a predefined schema, so we store
                in tender_number as default, but could be queried from either column'''
                new_tender.tender_number = extracted_tender_number
                print(f"[INFO] Storing {extracted_tender_number} in tender_number for source {new_source}")
        
        db.session.add(new_tender)
        db.session.flush()  # Get ID before commit
    
    # Process uploaded files
    processed_files, errors = [], []
    main_document_content = None
    all_documents_content = []  # New: collect all content
    processed_documents = []  # Store document objects for hyperlink extraction
    
    for index, file in enumerate(files):
        file_extension = os.path.splitext(file.filename)[1].lower()
        if file_extension not in ['.pdf', '.txt']:
            errors.append(f"{file.filename}: Only PDF and TXT files are supported")
            continue

        try:
            file_data = save_uploaded_file(file)
            is_primary = (index == 0)
            
            document = Document(
                filename=file_data['filename'],
                original_filename=file_data['original_filename'],
                file_path=file_data['file_path'],
                file_type=file_data['file_type'],
                file_size=file_data['file_size'],
                content_text=file_data['content_text'],
                is_primary=is_primary,
                tender_id=new_tender.id
            )
            db.session.add(document)
            processed_documents.append(document)  # Store for hyperlink extraction

            if is_primary:
                main_document_content = file_data['content_text']
            
            # Collect all document content but limit each to prevent overflow
            if file_data['content_text']:
                # Limit each document to 150k characters to prevent processing issues
                limited_content = file_data['content_text'][:150000]
                all_documents_content.append({
                    'content': limited_content,
                    'filename': file.filename,
                    'is_primary': is_primary
                })
            
            processed_files.append(file.filename)
        
        except Exception as e:
            errors.append(f"{file.filename}: {str(e)}")

    # Extract overview with intelligent content combination AND hyperlink support
    if all_documents_content:
        try:
            if len(all_documents_content) == 1:
                # Single document - use as is
                content_for_overview = all_documents_content[0]['content']
                print(f"[INFO] Single document processing: {len(content_for_overview):,} characters")
            else:
                # Multiple documents - smart combination strategy
                print(f"[INFO] Processing {len(all_documents_content)} documents")
                
                # Start with primary document
                primary_doc = next((doc for doc in all_documents_content if doc['is_primary']), all_documents_content[0])
                content_for_overview = primary_doc['content']
                
                # Add sections from other documents
                for doc in all_documents_content:
                    if not doc['is_primary']:
                        # Add a separator and portion of additional documents
                        additional_content = f"\n\n--- ADDITIONAL DOCUMENT: {doc['filename']} ---\n"
                        additional_content += doc['content'][:50000]  # Limit additional docs to 80k chars
                        content_for_overview += additional_content
                
                # Final safety check on total content length
                if len(content_for_overview) > 400000:
                    print(f"[WARN] Combined content very large ({len(content_for_overview):,} chars), truncating")
                    content_for_overview = content_for_overview[:400000]
                    # Try to end at a sentence boundary
                    last_period = content_for_overview.rfind('.')
                    if last_period > 300000:
                        content_for_overview = content_for_overview[:last_period + 1]
                
                print(f"[INFO] Combined content length: {len(content_for_overview):,} characters")
            
            # Get the primary document path for hyperlink extraction
            primary_doc_path = None
            primary_doc = next((doc for doc in processed_documents if doc.is_primary), None)
            if primary_doc and primary_doc.file_path and os.path.exists(primary_doc.file_path):
                primary_doc_path = primary_doc.file_path
                print(f"[INFO] Using primary document for hyperlink extraction: {primary_doc_path}")
            
            # Extract overview data WITH HYPERLINK SUPPORT
            overview_data = extract_tender_overview(content_for_overview, primary_doc_path)
            
            # Apply overview data to tender record
            new_tender.due_date = overview_data.get('due_date')
            new_tender.bid_opening_date = overview_data.get('bid_opening_date')
            new_tender.bid_offer_validity = overview_data.get('bid_offer_validity')
            new_tender.emd_amount = overview_data.get('emd_amount')
            new_tender.qualification_criteria = overview_data.get('qualification_criteria')
            new_tender.question_deadline = overview_data.get('question_deadline')
            new_tender.reverse_auction = overview_data.get('reverse_auction')
            new_tender.rejection_criteria = overview_data.get('rejection_criteria')
            new_tender.msme_preferences = overview_data.get('msme_preferences')
            new_tender.border_country_clause = overview_data.get('border_country_clause')
            
            # IMPORTANT: Only set tender_number from overview if not already set
            # Why this check: We may have already set tender_number from Gemini extraction
            # Overview extraction might provide a different format, so we preserve the original
            # unless no tender_number was extracted from the document title
            if not new_tender.tender_number:
                new_tender.tender_number = overview_data.get('tender_number')
            
            new_tender.organization_details = overview_data.get('organization_details')
            new_tender.performance_security = overview_data.get('performance_security')
            new_tender.payment_terms = overview_data.get('payment_terms')
            new_tender.technical_specifications = overview_data.get('technical_specifications')
            new_tender.scope_of_work = overview_data.get('scope_of_work')
            new_tender.performance_standards = overview_data.get('performance_standards')
            new_tender.evaluation_criteria = overview_data.get('evaluation_criteria')
            new_tender.documentation_requirements = overview_data.get('documentation_requirements')
            new_tender.additional_details = overview_data.get('additional_details')
            
            print(f"[INFO] Overview extraction completed successfully")

            # --- Insert Products (if available) for uploaded tender ---
            try:
                products_data = overview_data.get('products_table') or []
                if isinstance(products_data, list) and len(products_data) > 0:
                    print(f"[DEBUG] Inserting {len(products_data)} products for Tender ID={new_tender.id}")
                    for p in products_data:
                        product = Product(
                            tender_id=new_tender.id,
                            product_name=p.get('product_name', 'Not specified'),
                            quantity=p.get('quantity', 'Not specified'),
                            delivery_days=p.get('delivery_days', 'Not specified'),
                            consignee_name=p.get('consignee_name', 'Not specified'),
                            delivery_address=p.get('delivery_address', 'Not specified'),
                            specification_link=p.get('specification_link') or None
                        )
                        db.session.add(product)
                    print(f"[DEBUG] Products queued for insert for Tender ID={new_tender.id}")
                else:
                    print("[INFO] No product data found in overview_data for uploaded tender.")
            except Exception as e:
                print(f"[ERROR] Failed to insert products for uploaded tender: {e}")
                import traceback
                print(traceback.format_exc())
                # Continue — we still want to commit other data

        except Exception as e:
            print(f"[ERROR] Overview extraction failed: {e}")
            import traceback
            traceback.print_exc()
            # Continue without overview data rather than failing the entire upload
            print("[WARN] Continuing without overview data")
    
    if processed_files:
        db.session.commit()
        return {
            'success': True,
            'tender_id': new_tender.id,
            'tender_action': 'updated' if existing_tender else 'created',
            'source': new_tender.source,
            'processed_files': processed_files,
            'errors': errors
        }
    else:
        db.session.rollback()
        return {
            'success': False,
            'errors': errors or ['No files were processed successfully']
        }

def debug_tender_data(tender_id):
    """Debug function to check tender data availability"""
    tender = Tender.query.get(tender_id)
    if not tender:
        print(f"[DEBUG] No tender found with ID {tender_id}")
        return False
    
    documents = Document.query.filter_by(tender_id=tender_id).all()
    print(f"[DEBUG] Found {len(documents)} documents for tender {tender_id}")
    
    for doc in documents:
        content_length = len(doc.content_text) if doc.content_text else 0
        print(f"[DEBUG] Document {doc.id}: {doc.original_filename}, Content length: {content_length}")
        if content_length > 0:
            print(f"[DEBUG] First 200 chars: {doc.content_text[:200]}...")
    
    return len(documents) > 0

def chunk_tender_documents(tender_id, chunk_size=1000, overlap=150):  # Increased chunk size
    """Enhanced chunking with better overlap and text processing"""
    print(f"[SERVICES] Chunking documents for tender {tender_id}", flush=True)
    start_time = time.time()  # Add timing
    
    try:
        documents = Document.query.filter_by(tender_id=tender_id).all()
        if not documents:
            print(f"[WARN] No documents found for tender {tender_id}", flush=True)
            return []
            
        chunks = []
        for doc in documents:
            if not doc.content_text or not doc.content_text.strip():
                print(f"[WARN] Empty content in document {doc.id}", flush=True)
                continue
            
            # More aggressive cleaning for speed
            content = re.sub(r'\s+', ' ', doc.content_text.strip())  # Single line cleanup
            
            # Create larger chunks with better boundaries
            step = chunk_size - overlap
            for i in range(0, len(content), step):
                chunk_end = min(i + chunk_size, len(content))
                chunk_text = content[i:chunk_end]
                
                # Better boundary detection
                if chunk_end < len(content) and '.' in chunk_text[-100:]:
                    last_period = chunk_text.rfind('.', max(0, len(chunk_text) - 100))
                    if last_period > len(chunk_text) * 0.7:
                        chunk_text = chunk_text[:last_period + 1]
                
                if len(chunk_text.strip()) > 150:  # Increased minimum size
                    chunks.append({
                        "text": chunk_text.strip(),
                        "doc_id": doc.id,
                        "doc_name": doc.original_filename,
                        "start_pos": i,
                        "chunk_id": len(chunks)
                    })
        
        elapsed = time.time() - start_time
        print(f"[INFO] Created {len(chunks)} chunks in {elapsed:.2f}s", flush=True)
        return chunks
        
    except Exception as e:
        print(f"[ERROR] Error chunking documents for tender {tender_id}: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return []

def create_embeddings(chunks):
    """Create OpenAI embeddings with larger batches for speed"""
    print(f"[DEBUG] Creating embeddings for {len(chunks)} chunks", flush=True)
    start_time = time.time()
    
    openai.api_key = current_app.config["OPENAI_API_KEY"]
    if not chunks:
        print("[WARN] No chunks provided for embedding creation", flush=True)
        return np.array([]), []

    try:
        texts = []
        valid_chunks = []

        for chunk in chunks:
            if isinstance(chunk, dict) and "text" in chunk:
                text = chunk["text"]
            else:
                text = str(chunk)

            if text and text.strip() and len(text.strip()) > 50:
                # Truncate very long texts to avoid API limits
                if len(text) > 8000:
                    text = text[:8000] + "..."
                texts.append(text.strip())
                valid_chunks.append(chunk)

        if not texts:
            print("[WARN] No valid text found in chunks", flush=True)
            return np.array([]), []

        print(f"[DEBUG] Creating embeddings for {len(texts)} text chunks", flush=True)

        model_name = "text-embedding-3-small"
        batch_size = 100  # Increased batch size for speed
        all_embeddings = []

        total_batches = (len(texts) + batch_size - 1) // batch_size
        for i in range(0, len(texts), batch_size):
            batch_num = (i // batch_size) + 1
            batch_texts = texts[i:i + batch_size]
            
            batch_start = time.time()
            response = openai.embeddings.create(
                input=batch_texts,
                model=model_name
            )
            batch_embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(batch_embeddings)
            
            batch_time = time.time() - batch_start
            print(f"[DEBUG] Batch {batch_num}/{total_batches} completed in {batch_time:.2f}s", flush=True)

        embeddings = np.array(all_embeddings)
        elapsed = time.time() - start_time
        print(f"[INFO] Created embeddings shape: {embeddings.shape} in {elapsed:.2f}s", flush=True)

        return embeddings, valid_chunks

    except Exception as e:
        print(f"[ERROR] Error creating embeddings: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return np.array([]), []


def store_embeddings_faiss(tender_id, embeddings, chunks):
    """Enhanced FAISS storage with better indexing and timing"""
    print(f"[SERVICES] Storing embeddings for tender {tender_id}", flush=True)
    start_time = time.time()
    
    try:
        if len(embeddings) == 0:
            print(f"[WARN] No embeddings to store for tender {tender_id}", flush=True)
            return False
            
        # Normalize embeddings for cosine similarity
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1  # Avoid division by zero
        embeddings_normalized = embeddings / norms
        
        # Use more efficient index for larger datasets
        dimension = embeddings.shape[1]
        if len(embeddings) > 1000:
            # Use IVF index for faster search on large datasets
            nlist = min(100, len(embeddings) // 10)
            quantizer = faiss.IndexFlatIP(dimension)
            index = faiss.IndexIVFFlat(quantizer, dimension, nlist)
            index.train(embeddings_normalized.astype('float32'))
            index.add(embeddings_normalized.astype('float32'))
            index_type = "IVF"
        else:
            # Use flat index for smaller datasets
            index = faiss.IndexFlatIP(dimension)
            index.add(embeddings_normalized.astype('float32'))
            index_type = "Flat"
        
        vector_stores[tender_id] = {
            "index": index,
            "chunks": chunks,
            "embeddings": embeddings_normalized,
            "created_at": time.time(),
            "index_type": index_type
        }
        
        elapsed = time.time() - start_time
        print(f"[INFO] Stored {len(embeddings)} embeddings in {elapsed:.2f}s (type: {index_type})", flush=True)
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Error storing embeddings for tender {tender_id}: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return False

def retrieve_top_chunks(question, tender_id, top_k=5, similarity_threshold=0.1):
    """Enhanced retrieval with better timing and debugging"""
    print(f"[SERVICES] Retrieving chunks for tender {tender_id}", flush=True)
    start_time = time.time()
    
    # Check if vector store exists, if not build it
    store = vector_stores.get(tender_id)
    if not store:
        print(f"[DEBUG] Building vector store for tender {tender_id}", flush=True)
        build_start = time.time()
        
        # Build vector store with timing
        chunks = chunk_tender_documents(tender_id)
        if not chunks:
            print(f"[ERROR] No chunks available for tender {tender_id}", flush=True)
            return []
            
        embeddings, valid_chunks = create_embeddings(chunks)
        if len(embeddings) == 0:
            print(f"[ERROR] No embeddings created for tender {tender_id}", flush=True)
            return []
            
        success = store_embeddings_faiss(tender_id, embeddings, valid_chunks)
        if not success:
            print(f"[ERROR] Failed to store embeddings for tender {tender_id}", flush=True)
            return []
            
        build_time = time.time() - build_start
        print(f"[INFO] Vector store built in {build_time:.2f}s", flush=True)
        store = vector_stores[tender_id]
    
    try:
        available_chunks = len(store["chunks"])
        actual_top_k = min(top_k, available_chunks)
        
        print(f"[DEBUG] Available: {available_chunks}, requesting: {actual_top_k}, type: {store.get('index_type', 'Unknown')}", flush=True)
        
        # Create question embedding
        embed_start = time.time()
        response = openai.embeddings.create(
            input=[question],
            model="text-embedding-3-small"
        )
        question_embedding = np.array([response.data[0].embedding])
        question_embedding = question_embedding / np.linalg.norm(question_embedding, axis=1, keepdims=True)
        embed_time = time.time() - embed_start
        
        # Perform similarity search
        search_start = time.time()
        similarities, indices = store["index"].search(question_embedding.astype('float32'), actual_top_k)
        search_time = time.time() - search_start
        
        print(f"[DEBUG] Embedding: {embed_time:.3f}s, Search: {search_time:.3f}s", flush=True)
        print(f"[DEBUG] Top similarities: {similarities[0][:3]}", flush=True)
        
        # Filter and extract chunks
        retrieved_chunks = []
        for idx, similarity in zip(indices[0], similarities[0]):
            if idx < 0 or idx >= len(store["chunks"]):
                continue
                
            if similarity < similarity_threshold:
                continue
                
            chunk = store["chunks"][idx]
            chunk_text = chunk["text"] if isinstance(chunk, dict) else str(chunk)
            
            retrieved_chunks.append({
                "text": chunk_text,
                "similarity": float(similarity),
                "doc_name": chunk.get("doc_name", "Unknown") if isinstance(chunk, dict) else "Unknown",
                "chunk_id": chunk.get("chunk_id", idx) if isinstance(chunk, dict) else idx
            })
        
        retrieved_chunks.sort(key=lambda x: x["similarity"], reverse=True)
        
        elapsed = time.time() - start_time
        print(f"[INFO] Retrieved {len(retrieved_chunks)} chunks in {elapsed:.2f}s", flush=True)
        
        return retrieved_chunks
        
    except Exception as e:
        print(f"[ERROR] Error in retrieval: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return []

def build_prompt_from_chunks(question, chunk_objects, max_context_length=15000):
    """Enhanced prompt building with chunk metadata and formatting instructions"""
    if not chunk_objects:
        print("[WARN] No chunks provided for prompt building")
        return f"""
You are a tender analysis assistant. 

Question: {question}

I don't have access to relevant tender document content for this question. The document content couldn't be retrieved properly. Please let the user know that the specific information they're asking about may not be available in the processed documents, and suggest they try rephrasing their question or contact support if the problem persists.
"""
    
    # Build context from chunks with metadata
    context_parts = []
    current_length = 0
    
    for i, chunk_obj in enumerate(chunk_objects):
        chunk_text = chunk_obj["text"] if isinstance(chunk_obj, dict) else str(chunk_obj)
        doc_name = chunk_obj.get("doc_name", "Document") if isinstance(chunk_obj, dict) else "Document"
        similarity = chunk_obj.get("similarity", 0) if isinstance(chunk_obj, dict) else 0
        
        # Format chunk with metadata
        chunk_section = f"""--- Relevant Section {i+1} (from {doc_name}, relevance: {similarity:.3f}) ---
{chunk_text}
---

"""
        
        if current_length + len(chunk_section) > max_context_length:
            break
            
        context_parts.append(chunk_section)
        current_length += len(chunk_section)
    
    context = "\n".join(context_parts)
    
    prompt = f"""You are a professional tender analysis assistant. Below are the most relevant sections from tender documents related to the user's question:

{context}

Question: {question}

Instructions:
1. Answer the question based ONLY on the information provided in the relevant sections above
2. Format your response with clear structure using:
   - **Bold headings** for main sections
   - • Bullet points for lists and multiple items
   - Clear paragraph breaks for readability
   - Highlight important numbers, dates, and amounts in **bold**
3. If the answer requires information not present in these sections, clearly state "This specific information is not available in the provided document sections"
4. When referencing information, mention which document section it comes from
5. Be precise and cite specific details from the context
6. If multiple sections contain related information, synthesize them coherently
7. Structure lengthy responses with subheadings and bullet points for easy scanning

Answer:"""
    
    print(f"[DEBUG] Built prompt with {len(chunk_objects)} chunks")
    print(f"[DEBUG] Context length: {len(context)} characters")
    print(f"[DEBUG] Total prompt length: {len(prompt)} characters")
    
    return prompt

def process_qa_interaction(tender_id, user_id, organization_id, question):
    """FIXED: Enhanced QA processing with proper RAG implementation"""
    print(f"[SERVICES] Processing QA for tender {tender_id}")
    print(f"[DEBUG] Question: '{question[:100]}...'")
    
    # Validate inputs
    if not question or not question.strip():
        return {'error': 'Question cannot be empty'}
    
    # Check if tender exists and has documents
    tender = Tender.query.get(tender_id)
    if not tender:
        return {'error': 'Tender not found'}
    
    documents = Document.query.filter_by(tender_id=tender_id).all()
    if not documents:
        return {'error': 'No documents found for this tender'}
    
    # Check if any document has content
    has_content = any(doc.content_text and doc.content_text.strip() for doc in documents)
    if not has_content:
        return {'error': 'No document content available for analysis'}
    
    try:
        model = init_gemini()
        
        # Use RAG to retrieve relevant chunks
        print("[DEBUG] Starting RAG retrieval...")
        chunk_objects = retrieve_top_chunks(question, tender_id, top_k=8, similarity_threshold=0.1)
        
        if not chunk_objects:
            print("[WARN] No relevant chunks found via RAG, using fallback")
            # Fallback: use beginning of documents
            fallback_content = []
            for doc in documents[:2]:
                if doc.content_text and len(doc.content_text.strip()) > 100:
                    fallback_content.append({
                        "text": doc.content_text[:3000],  # First 3000 chars
                        "doc_name": doc.original_filename,
                        "similarity": 0.0
                    })
            chunk_objects = fallback_content
        
        if not chunk_objects:
            return {'error': 'No relevant content could be found in the documents'}
        
        # Build prompt using RAG results
        prompt = build_prompt_from_chunks(question, chunk_objects)
        
        # Generate response
        print("[DEBUG] Generating AI response...")
        response = model.generate_content(prompt)
        answer = response.text
        
        # Store the interaction
        qa_interaction = QAInteraction(
            question=question,
            answer=answer,
            tender_id=tender_id,
            user_id=user_id
        )
        db.session.add(qa_interaction)
        db.session.commit()
        
        print(f"[INFO] QA interaction completed successfully")
        
        return {
            'success': True,
            'answer': answer,
            'id': qa_interaction.id,
            'debug_info': {
                'chunks_used': len(chunk_objects),
                'rag_used': True,
                'avg_similarity': np.mean([c.get('similarity', 0) for c in chunk_objects]) if chunk_objects else 0
            }
        }
        
    except Exception as e:
        print(f"[ERROR] Error processing QA: {e}")
        import traceback
        traceback.print_exc()
        return {'error': f'Error processing question: {str(e)}'}
        
def generate_risk_assessment(tender_id, user_id, organization_id):
    """Generate risk assessment for a tender"""
    model = init_gemini()
    
    # Get the tender
    tender = Tender.query.get(tender_id)
    if not tender:
        return {'error': 'Tender not found'}
    
    # Get documents for this tender
    documents = Document.query.filter_by(tender_id=tender_id).all()
    if not documents:
        return {'error': 'No documents found for this tender'}
    
    # Get user's constraints
    constraints = {
        'financial': [c.description for c in Constraint.query.filter_by(user_id=user_id, category='financial').all()],
        'technical': [c.description for c in Constraint.query.filter_by(user_id=user_id, category='technical').all()],
        'legal': [c.description for c in Constraint.query.filter_by(user_id=user_id, category='legal').all()],
        'other': [c.description for c in Constraint.query.filter_by(user_id=user_id, category='other').all()]
    }
    
    # Get service and product definition to include in risk assessment
    definition = ServiceProductDefinition.query.filter_by(user_id=user_id).first()
    service_product_text = definition.definition if definition else ""
    
    # Combine document content
    combined_content = ""
    for doc in documents:
        combined_content += f"\n\n--- DOCUMENT: {doc.original_filename} ---\n\n"
        combined_content += doc.content_text[:500000]  # Limit to avoid token limits
    
    # Create prompt for Gemini
    prompt = f"""
    You are a tender risk assessment assistant. Below are the contents from a tender document and the organizational constraints:
    
    TENDER DOCUMENT CONTENT:
    {combined_content[:100000]}  # Limiting overall content
    
    ORGANIZATIONAL PROFILE:
    {service_product_text}
    
    ORGANIZATIONAL CONSTRAINTS:
    
    Financial Constraints:
    {json.dumps(constraints['financial'])}
    
    Technical Constraints:
    {json.dumps(constraints['technical'])}
    
    Legal Constraints:
    {json.dumps(constraints['legal'])}
    
    Other Constraints:
    {json.dumps(constraints['other'])}
    
    Based on the tender document content, organizational profile, and organizational constraints, please identify and categorize potential risks into the following categories:
    1. Financial Risks
    2. Technical Risks
    3. Legal Risks
    4. Other Risks
    
    For each risk, provide:
    - A brief title
    - A detailed description
    - The severity level (high, medium, or low)
    - The potential impact
    - Suggested mitigation strategies
    - The related organizational constraint (if applicable)
    
    Format your response as a JSON object with the following structure:
    {{
        "risks": {{
            "financial": [
                {{
                    "title": "Risk title",
                    "description": "Detailed description of the risk",
                    "severity": "high|medium|low",
                    "impact": "Description of the potential impact",
                    "mitigation": "Suggested mitigation strategy",
                    "constraint": "Related organizational constraint (if applicable)"
                }}
            ],
            "technical": [...],
            "legal": [...],
            "other": [...]
        }}
    }}
    
    Return ONLY the JSON object, nothing else.
    """
    
    try:
        # Generate response from Gemini
        response = model.generate_content(prompt)
        
        # Parse response
        text_response = response.text
        json_match = re.search(r'({.*})', text_response.replace('\n', ' '), re.DOTALL)
            
        if json_match:
            json_str = json_match.group(1)
            risks_data = json.loads(json_str)
            
            # Ensure the structure is correct
            if 'risks' not in risks_data:
                risks_data = {'risks': risks_data}
            
            # Ensure all categories exist
            for category in ['financial', 'technical', 'legal', 'other']:
                if category not in risks_data['risks']:
                    risks_data['risks'][category] = []
            
            # Count risks by severity
            high_count = 0
            medium_count = 0
            low_count = 0
            total_count = 0
            
            for category in ['financial', 'technical', 'legal', 'other']:
                for risk in risks_data['risks'][category]:
                    total_count += 1
                    if risk['severity'] == 'high':
                        high_count += 1
                    elif risk['severity'] == 'medium':
                        medium_count += 1
                    elif risk['severity'] == 'low':
                        low_count += 1
            
            # Create risk assessment record
            risk_assessment = RiskAssessment(
                tender_id=tender_id,
                user_id=user_id,
                total_risks=total_count,
                high_risks=high_count,
                medium_risks=medium_count,
                low_risks=low_count
            )
            db.session.add(risk_assessment)
            db.session.flush()  # Get the ID without committing
            
            # Create individual risk records
            for category in ['financial', 'technical', 'legal', 'other']:
                for risk_data in risks_data['risks'][category]:
                    risk = Risk(
                        title=risk_data.get('title', 'Untitled Risk'),
                        description=risk_data.get('description', ''),
                        category=category,
                        severity=risk_data.get('severity', 'medium'),
                        impact=risk_data.get('impact', ''),
                        mitigation=risk_data.get('mitigation', ''),
                        related_constraint=risk_data.get('constraint', ''),
                        assessment_id=risk_assessment.id
                    )
                    db.session.add(risk)
            
            db.session.commit()
            
            # Return risk assessment data
            return {
                'success': True,
                'assessment_id': risk_assessment.id,
                'risks': risks_data['risks'],
                'summary': {
                    'total': total_count,
                    'high': high_count,
                    'medium': medium_count,
                    'low': low_count
                }
            }
        else:
            return {'error': 'Failed to parse AI response'}
                
    except Exception as e:
        print(f"Error generating risks: {e}")
        return {'error': f'Error generating risk assessment: {str(e)}'}

def generate_bidder_questions(tender_id, user_id, organization_id):
    """Generate bidder questions for a tender"""
    model = init_gemini()
    
    # Check if bidder questions already exist for this tender
    existing_question_set = BidderQuestionsSet.query.filter_by(
        tender_id=tender_id
    ).order_by(BidderQuestionsSet.generated_at.desc()).first()
    
    if existing_question_set:
        # Return existing questions from the database
        questions = []
        for q in existing_question_set.questions:
            questions.append({
                "question": q.question,
                "explanation": q.explanation,
                "category": q.category,
                "section_reference": q.section_reference
            })
        
        return {"success": True, "questions": questions, "new": False}
    
    # Get documents for the tender
    documents = Document.query.filter_by(tender_id=tender_id).all()
    if not documents:
        return {'error': 'No documents found for this tender'}
    
    # Get service and product definition for context
    definition = ServiceProductDefinition.query.filter_by(user_id=user_id).first()
    service_product_text = definition.definition if definition else ""
    
    try:
        # Combine document content
        combined_content = ""
        for doc in documents:
            combined_content += f"\n\n--- DOCUMENT: {doc.original_filename} ---\n\n"
            combined_content += doc.content_text[:500000]  # Limit to avoid token limits
        
        # Create prompt for Gemini
        prompt = f"""
        You are a tender analysis expert helping bidders prepare questions for the tender issuing authority.
        Below is the content from tender documents:
        
        {combined_content[:100000]}  # Limiting overall content
        
        ORGANIZATIONAL PROFILE OF BIDDER:
        {service_product_text}
        
        Based on the tender document content and the organizational profile, please generate a comprehensive list of questions that this bidder should ask the tender issuing authority for clarification.
        
        Focus on questions related to:
        1. Technical specifications that need clarification
        2. Evaluation criteria that seem ambiguous
        3. Timeline or logistics issues that need clarification
        4. Payment terms and conditions that require more details
        5. Qualification requirements that could be interpreted differently
        6. Scope of work areas that need further explanation
        7. Any potential mismatches between the bidder's services/products and tender requirements
        
        For each question:
        - Provide a clear, specific question
        - Include a brief explanation of why this clarification is needed
        - Reference the specific section/page where the ambiguity exists (if possible)
        
        Format your response as a JSON array of questions, where each question is an object with these properties:
        - "question": The actual question text
        - "explanation": Why this clarification is important
        - "category": The category from the list above (technical, evaluation, timeline, payment, qualification, scope)
        - "section_reference": The document section or page reference (if identifiable)
        
        The JSON should look like:
        {{
            "questions": [
                {{
                    "question": "...",
                    "explanation": "...",
                    "category": "technical",
                    "section_reference": "Section 3.2, Page 12"
                }},
                ...
            ]
        }}
        
        Return ONLY the JSON object, nothing else.
        """
        
        # Generate response from Gemini
        response = model.generate_content(prompt)
        
        # Parse response
        text_response = response.text
        json_match = re.search(r'({.*})', text_response.replace('\n', ' '), re.DOTALL)
            
        if json_match:
            json_str = json_match.group(1)
            questions_data = json.loads(json_str)
            
            # Ensure the structure is correct
            if 'questions' not in questions_data:
                questions_data = {'questions': questions_data}
            
            # Create a new question set in the database
            question_set = BidderQuestionsSet(
                tender_id=tender_id,
                user_id=user_id
            )
            db.session.add(question_set)
            db.session.flush()  # Get the ID without committing
            
            # Add individual questions to the database
            for question_data in questions_data['questions']:
                bidder_question = BidderQuestion(
                    question=question_data.get('question', ''),
                    explanation=question_data.get('explanation', ''),
                    category=question_data.get('category', ''),
                    section_reference=question_data.get('section_reference', ''),
                    question_set_id=question_set.id
                )
                db.session.add(bidder_question)
            
            # Commit all changes
            db.session.commit()
                
            return {"success": True, "questions": questions_data['questions'], "new": True}
        else:
            return {'error': 'Failed to parse AI response'}
                
    except Exception as e:
        print(f"Error generating bidder questions: {e}")
        return {'error': f'Error generating questions: {str(e)}'}
    
# -------------------------------------------------------------------------------------------------------------

def analyze_gem_tender_service(pdf_path, gem_tender, user_id, organization_id):
    """
    Service to extract tender overview from PDF using Gemini AI.
    Skip analysis if tender already exists in Tender table.
    """
    try:
        tender_number = getattr(gem_tender, 'tender_id', None)

        # Check if tender already exists in Tender table, if yes then fetch the record
        tender = Tender.query.filter_by(tender_number=tender_number).first()
        if tender:
            return tender 
 
        # else : if tender does not exist in Tender table, proceed with analysis
        else:
            file_extension = os.path.splitext(pdf_path)[1].lower()
            
            text_content = extract_text_from_file(pdf_path, file_extension)
            print(f"[DEBUG] Extracted text length: {len(text_content)}")

            if not text_content.strip():
                raise ValueError("No text extracted from tender PDF")

            overview_data = extract_tender_overview(text_content,pdf_path)
            # print("[DEBUG] Data returned from Gemini:")
            # print(overview_data)

            if not overview_data:
                raise ValueError("Gemini returned no overview data")

            tender_number = overview_data.get('tender_number') or tender_number

            # Clean tender number before storing
            cleaned_tender_number = re.sub(
                r'\s*(?:dated|Dated|Date|date|Dt\.?)[:\s]*\d{1,2}[-/]\d{1,2}[-/]\d{2,4}',  # remove date parts
                '', 
                tender_number
            )

            # Remove leftover brackets, parentheses, or extra spaces
            cleaned_tender_number = re.sub(r'[\(\)\[\]\{\},\.]+', '', cleaned_tender_number).strip()

            # create new tender record
            tender = Tender(
                title=overview_data.get('title') or f"Tender {cleaned_tender_number}",
                description=overview_data.get('description') or getattr(gem_tender, 'description', None),
                due_date=overview_data.get('due_date'),
                bid_opening_date=overview_data.get('bid_opening_date'),
                bid_offer_validity=overview_data.get('bid_offer_validity'),
                emd_amount=overview_data.get('emd_amount'),
                estimated_cost=overview_data.get('estimated_cost'),
                question_deadline=overview_data.get('question_deadline'),
                qualification_criteria=overview_data.get('qualification_criteria'),
                reverse_auction=overview_data.get('reverse_auction'),
                rejection_criteria=overview_data.get('rejection_criteria'),
                msme_preferences=overview_data.get('msme_preferences'),
                border_country_clause=overview_data.get('border_country_clause'),
                tender_number=cleaned_tender_number,
                tender_reference_number='-',
                organization_details=overview_data.get('organization_details'),
                performance_security=overview_data.get('performance_security'),
                payment_terms=overview_data.get('payment_terms'),
                technical_specifications=overview_data.get('technical_specifications'),
                scope_of_work=overview_data.get('scope_of_work'),
                performance_standards=overview_data.get('performance_standards'),
                evaluation_criteria=overview_data.get('evaluation_criteria'),
                documentation_requirements=overview_data.get('documentation_requirements'),
                additional_details=overview_data.get('additional_details'),
                source='GEM_Analyze',
                user_id=user_id,
                organization_id=organization_id
            )
            db.session.add(tender)
            db.session.commit()

            # --- Insert Products (if available) ---
            products_data = overview_data.get('products_table') or []
            if isinstance(products_data, list) and len(products_data) > 0:
                print(f"[DEBUG] Inserting {len(products_data)} products for Tender ID={tender.id}")
                for p in products_data:
                    # Defensive defaults
                    product = Product(
                        tender_id=tender.id,
                        product_name=p.get('product_name', 'Not specified'),
                        quantity=p.get('quantity', 'Not specified'),
                        delivery_days=p.get('delivery_days', 'Not specified'),
                        consignee_name=p.get('consignee_name', 'Not specified'),
                        delivery_address=p.get('delivery_address', 'Not specified'),
                        specification_link=p.get('specification_link', None)
                    )
                    db.session.add(product)

                db.session.commit()
                print(f"[DEBUG] Products successfully inserted for Tender ID={tender.id}")
            else:
                print("[INFO] No product data found in overview_data.")

            # Insert Document record
            document = Document(
                filename=os.path.basename(pdf_path),
                original_filename=os.path.basename(pdf_path),
                file_path=pdf_path,
                file_type=file_extension.replace('.', ''), 
                file_size=os.path.getsize(pdf_path),
                content_text=text_content,
                is_primary=True,
                tender_id=tender.id
            )
            db.session.add(document)
            db.session.commit()

            print(f"[DEBUG] Tender and Document insertion completed. Tender ID={tender.id}, Document ID={document.id}")
            return tender

    except Exception as e:
        print(f"[ERROR] analyze_gem_tender_service failed: {e}")
        import traceback
        print(traceback.format_exc())
        raise e
    
import logging
from threading import Thread
import os

def run_gem_nlp_api_manual(organization_id, search_keyword=None, max_tenders=10):
    """
    Run GeM tender fetching and other tender sources using their respective scripts
    Returns (success: bool, result: dict)
    """
    try:
        # Log the request
        logger = logging.getLogger(__name__)
        logger.info(f"Starting tender fetching for Organization (ID: {organization_id})")
        logger.info(f"Parameters - Search Keyword: '{search_keyword}', Max Tenders: {max_tenders}")
        
        # Validate inputs
        try:
            max_tenders = int(max_tenders)
            if max_tenders < 1 or max_tenders > 100:
                return False, {'error': 'Max tenders must be between 1 and 30'}
        except ValueError:
            return False, {'error': 'Max tenders must be a number'}
                    
        # Run in background thread
        def run_all_tender_fetching():
            try:
                # Prepare keyword argument
                keyword_arg = "none" if search_keyword is None else search_keyword
                
                # Call GeM NLP API first
                logger.info(f"Step 1/3: Starting GeM tender fetching")
                import gem_nlp_api as gem_script
                gem_script.main_cli(
                    search_keyword=keyword_arg,
                    max_tenders=max_tenders,
                    organization_id=organization_id,
                    domain_keywords=None
                )
                logger.info("GeM tender fetching completed successfully")
                
                # Call MahaTenders second
                logger.info(f"Step 2/3: Starting MahaTenders fetching")
                import mahatenders as maha_script
                maha_script.main_cli(
                    search_keyword=keyword_arg,
                    max_tenders=max_tenders,
                    organization_id=organization_id,
                    domain_keywords=None
                )
                logger.info("MahaTenders fetching completed successfully")
                
                # Call CPPP Tenders third
                logger.info(f"Step 3/3: Starting CPPP Tenders fetching")
                import cppp_tenders as cppp_script
                cppp_script.main_cli(
                    search_keyword=keyword_arg,
                    max_tenders=max_tenders,
                    organization_id=organization_id,
                    domain_keywords=None
                )
                logger.info("CPPP Tenders fetching completed successfully")
                
                logger.info("All tender fetching completed successfully")
                
            except ImportError as e:
                logger.error(f"Error importing tender scripts: {str(e)}", exc_info=True)
            except Exception as e:
                logger.error(f"Error in tender fetching execution: {str(e)}", exc_info=True)
        
        # Start the background thread
        thread = Thread(target=run_all_tender_fetching)
        thread.daemon = True
        thread.start()
        
        return True, {
            'success': True,
            'message': 'Tender fetching started in the background. This may take a few minutes.',
            'details': f'Searching across 3 sources (GeM, MahaTenders, CPPP) for "{search_keyword if search_keyword else "all tenders"}" (Max: {max_tenders} tenders per source)',
            'sources': ['GeM Tenders', 'MahaTenders', 'CPPP Tenders']
        }
        
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Error in fetch_all_tenders: {str(e)}", exc_info=True)
        return False, {'error': str(e)}
    