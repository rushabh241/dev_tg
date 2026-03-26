# tender_pdf_utils.py

import io
import re
from weasyprint import HTML


def split_sentences_preserve_numbers(text):
    """
    Split text by periods ('.') into sentences while preserving:
    - Version/paragraph numbers like 3.12.32, 303.12, 7.8.1
    - Codes like DPM-2009.
    - List numbers like "1. text" (these are kept as part of the sentence)
    Returns a list of sentence strings (trimmed).
    """
    if not text:
        return []

    sentences = []
    current = ""
    i = 0
    L = len(text)

    while i < L:
        ch = text[i]
        current += ch

        if ch == '.':
            # Determine whether this '.' ends a sentence or is part of a numeric/code token.
            is_part_of_number = False

            # Lookback digits before the dot
            j = i - 1
            digits_before = 0
            while j >= 0 and text[j].isdigit():
                digits_before += 1
                j -= 1

            # Case A: version-like 7.8.1 or 303.12 (digits after dot)
            if digits_before > 0 and (i + 1 < L and text[i + 1].isdigit()):
                is_part_of_number = True

            # Case B: code pattern like DPM-2009.  (letters + '-' + digits + '.')
            if not is_part_of_number:
                lookback = text[max(0, i - 20): i + 1]  # small context
                if re.search(r'[A-Za-z]+-\d+\.$', lookback):
                    is_part_of_number = True

            # Case C: list number at start of sentence or after whitespace, like "1. " or "23. "
            if not is_part_of_number:
                k = i - 1
                digit_seq = ""
                while k >= 0 and text[k].isdigit():
                    digit_seq = text[k] + digit_seq
                    k -= 1
                if digit_seq:
                    if k < 0 or text[k] in [' ', '\n', '\r', '\t']:
                        if i + 1 < L and text[i + 1] == ' ':
                            is_part_of_number = True

            # Case D: lettered list like "a. ", "b. ", "c. " (ignore as sentence boundary)
            if not is_part_of_number:
                if i >= 1 and text[i - 1].isalpha() and text[i - 1].islower():
                    if (i - 2 < 0 or text[i - 2] in [' ', '\n', '\r', '\t']) and (i + 1 < L and text[i + 1] == ' '):
                        is_part_of_number = True

            # Case E: Common abbreviations that should not split
            abbreviations = ['Rs']
            if not is_part_of_number:
                token_match = re.search(r'(\b\w+)\.$', current)
                if token_match and token_match.group(1) in abbreviations:
                    is_part_of_number = True

            # If not part of number, consider it a sentence terminator only if followed by space/newline/end
            if not is_part_of_number:
                if i + 1 >= L or text[i + 1] in [' ', '\n', '\r', '\t']:
                    sentences.append(current.strip())
                    current = ""

        i += 1

    if current.strip():
        sentences.append(current.strip())

    return [s for s in sentences if s]


def format_text(text):
    """
    Format text for PDF generation with bullets, bold headings, and line breaks.
    Block-aware indentation: indentation applied only to list-like lines that follow
    a header (line ending with ':') within the SAME block (blocks separated by blank lines).
    """
    if not text or text.strip() == '':
        return ''

    # Normalize whitespace and convert bold markdown to HTML
    text = text.strip()
    text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\r\n', '\n', text)
    text = re.sub(r'\n{2,}', '\n\n', text)

    # Split into blocks
    blocks = re.split(r'\n\s*\n', text)

    all_formatted_blocks = []

    for block in blocks:
        if not block or block.strip() == '':
            continue

        raw_lines = [ln.rstrip() for ln in block.split('\n') if ln.strip() != '']
        raw_lines = [re.sub(r'^[\s\-\*\u2022\u2013\u2014]+', '', ln).strip() for ln in raw_lines]

        formatted_lines = []

        colon_lines = [ln for ln in raw_lines if ':' in ln]
        if len(colon_lines) > 1:
            for ln in raw_lines:
                if re.match(r'^(?:\d+|[a-z])\.\s+', ln, re.IGNORECASE):
                    formatted_lines.append(ln)
                    continue

                if ':' in ln:
                    h, v = ln.split(':', 1)
                    heading = h.strip()
                    value = v.strip()
                    sentences = split_sentences_preserve_numbers(value)
                    if sentences:
                        if len(sentences) == 1:
                            formatted_lines.append(f"• <b>{heading}:</b> {sentences[0]}")
                        else:
                            formatted_lines.append(f"<b>{heading}:</b>")
                            for s in sentences:
                                formatted_lines.append(f"• {s}")
                    else:
                        formatted_lines.append(f"• <b>{heading}:</b>")
                else:
                    if re.match(r'^(?:\d+|[a-z])\.\s+', ln, re.IGNORECASE):
                        formatted_lines.append(ln)
                    else:
                        sentences = split_sentences_preserve_numbers(ln)
                        if len(sentences) <= 1:
                            formatted_lines.append(f"• {ln}")
                        else:
                            for s in sentences:
                                formatted_lines.append(f"• {s}")
        else:
            for ln in raw_lines:
                if re.match(r'^(?:\d+|[a-z])\.\s+', ln, re.IGNORECASE):
                    formatted_lines.append(ln)
                    continue

                if ':' in ln:
                    h, v = ln.split(':', 1)
                    heading = h.strip()
                    content = v.strip()
                    if content == '':
                        formatted_lines.append(f"• <b>{heading}:</b>")
                        continue

                    has_numbered_list = re.search(r'^\d+\.\s+', content) or re.search(r'\s+\d+\.\s+', content)
                    if has_numbered_list:
                        formatted_lines.append(f"<b>{heading}:</b>")
                        items = re.split(r'(?=\d+\.\s+)', content)
                        for item in items:
                            item = item.strip()
                            if item:
                                formatted_lines.append(item)
                    else:
                        sentences = split_sentences_preserve_numbers(content)
                        if not sentences:
                            formatted_lines.append(f"• <b>{heading}:</b>")
                        elif len(sentences) == 1:
                            formatted_lines.append(f"• <b>{heading}:</b> {sentences[0]}")
                        else:
                            formatted_lines.append(f"<b>{heading}:</b>")
                            for s in sentences:
                                formatted_lines.append(f"• {s}")
                else:
                    sentences = split_sentences_preserve_numbers(ln)
                    if not sentences:
                        continue
                    if len(sentences) == 1:
                        formatted_lines.append(f"• {sentences[0]}")
                    else:
                        for s in sentences:
                            formatted_lines.append(f"• {s}")

        # ---- BLOCK-AWARE indentation pass ----
        processed = []
        indent_stack = []

        def is_numeric_line(s):
            return bool(re.match(r'^\d+\.\s+', s))

        def is_lettered_line(s):
            return bool(re.match(r'^[a-z]\.\s+', s, re.IGNORECASE))

        def is_bullet_line(s):
            return s.startswith('•') or s.startswith('-') or s.startswith('*')

        for ln in formatted_lines:
            s = ln.strip()

            is_header_line = (
                bool(re.search(r':\s*$', s))
                or bool(re.search(r':</b>$', s))
                or bool(re.search(r':</strong>$', s))
            )

            has_colon_inside = ':' in s

            if is_header_line:
                processed.append(s)
                indent_stack.append({'type': 'block'})
                continue

            if is_numeric_line(s) and s.endswith(':'):
                processed.append(s)
                indent_stack.append({'type': 'numbered'})
                continue

            if (is_bullet_line(s) or is_numeric_line(s) or is_lettered_line(s)) and has_colon_inside:
                processed.append(s)
                indent_stack.append({'type': 'block'})
                continue

            if indent_stack:
                top = indent_stack[-1]

                if top['type'] == 'numbered' and is_lettered_line(s):
                    processed.append('&emsp;' + s)
                    continue

                if top['type'] == 'block' and (is_bullet_line(s) or is_numeric_line(s) or is_lettered_line(s)):
                    if ':' in s:
                        processed.append(s)
                        indent_stack.append({'type': 'block'})
                    else:
                        processed.append('&emsp;' + s)
                    continue

                if not (is_bullet_line(s) or is_numeric_line(s) or is_lettered_line(s)):
                    indent_stack.pop()
                    processed.append(s)
                    continue

            processed.append(s)

        all_formatted_blocks.extend(processed)

    cleaned = []
    for fl in all_formatted_blocks:
        ln = re.sub(r'^(?:[\u2022\-\*\u2013\u2014]\s*){2,}', '• ', fl).strip()
        cleaned.append(ln)

    return '<br>'.join(cleaned)


def format_text_for_table(text):
    """
    Wrapper function that also handles 'Not specified' cases.
    """
    if not text:
        return ''

    stripped = text.strip()
    if stripped == '' or stripped.lower() == 'not specified':
        return text

    return format_text(text)


def make_links_clickable(text):
    """
    Converts URLs in text to clickable HTML links.
    """
    if not text:
        return 'Not specified'

    url_pattern = r'(https?://[^\s<]+)'
    text_with_links = re.sub(url_pattern, r'<a href="\1" target="_blank">\1</a>', text)
    text_with_links = text_with_links.replace('\n', '<br>')
    return text_with_links


def build_product_rows(products):
    """
    Build HTML rows for products table.
    """
    rows = ''.join([
        f"""
        <tr>
            <td>{p.product_name or 'Not Specified'}</td>
            <td>{p.quantity or 'Not Specified'}</td>
            <td>{p.delivery_days or 'Not Specified'}</td>
            <td>{p.consignee_name or 'Not Specified'}</td>
            <td>{p.delivery_address or 'Not Specified'}</td>
            <td>
                {(
                    "<br>".join(
                        (
                            lambda link: (
                                f'<a href="{link.strip()}" target="_blank" class="view-link">📄 ' +
                                (
                                    "Specification Document" if link.lower().endswith(".pdf")
                                    else "BOQ Document" if any(link.lower().endswith(ext) for ext in [".xls", ".xlsx", ".csv"])
                                    else "Document"
                                ) +
                                '</a>'
                            )
                        )(link.strip())
                        for link in (p.specification_link.split(',') if p.specification_link else [])
                        if link.strip()
                    )
                )
                if p.specification_link and not any(word in p.specification_link.lower() for word in ["no", "not"])
                else '——'}
            </td>
        </tr>
        """
        for p in products
    ])

    return rows or '<tr><td colspan="6">No products found</td></tr>'


def build_documents_html(documents):
    """
    Build HTML list for attached documents.
    """
    if not documents:
        return '<li>No documents found</li>'

    return ''.join(f'<li>{doc.original_filename}</li>' for doc in documents)


def build_tender_html(tender, products, documents, logo_path):
    """
    Build full HTML used for PDF generation.
    """
    product_rows = build_product_rows(products)
    documents_html = build_documents_html(documents)

    additional_details_html = make_links_clickable(tender.additional_details or 'Not specified')

    html_body = f"""
    <!doctype html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            @page {{
                size: A4;
                margin-top: 2cm;
                margin-right: 2cm;
                margin-bottom: 0.5cm;
                margin-left: 2cm;
            }}

            body {{
                font-family: Arial, Helvetica, sans-serif;
                line-height: 1.6;
                color: #333;
                font-size: 12px;
                margin: 0;
                -webkit-print-color-adjust: exact;
                box-sizing: border-box;
            }}

            .watermark {{
                position: fixed;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%) rotate(-45deg);
                opacity: 0.10;
                z-index: 0;
                width: 90%;
                height: auto;
                pointer-events: none;
            }}

            .container, .section-box, .section-group, .footer-box {{
                position: relative;
                z-index: 1;
            }}

            .header-logo {{
                position: fixed;
                top: -1cm;
                right: -1cm;
                height: 35px;
                width: auto;
                z-index: 1000;
            }}

            .container {{
                max-width: 800px;
                margin: 0 auto;
                padding: 20px 0;
            }}

            h1 {{
                color: #4B3B8C;
                border-bottom: 3px solid #4B3B8C;
                padding-bottom: 10px;
                font-size: 1.6em;
                margin-top: 0;
            }}

            h2 {{
                color: #4B3B8C;
                margin-top: 30px;
                font-size: 1.2em;
                page-break-after: avoid;
            }}

            table {{
                width: 100%;
                border-collapse: collapse;
                margin: 10px 0;
                page-break-inside: auto;
                break-inside: auto;
            }}

            th, td {{
                padding: 8px;
                border: 1px solid #ccc;
                page-break-inside: auto !important;
                break-inside: auto !important;
                vertical-align: top;
            }}

            th {{
                background-color: #f4f4f4;
                font-weight: bold;
            }}

            td.label {{
                font-weight: bold;
                background-color: #f8f9fa;
                width: 30%;
            }}

            .section-group {{
                page-break-inside: avoid;
                break-inside: avoid;
                margin-bottom: 20px;
            }}

            .footer-box {{
                margin-top: 40px;
                padding: 20px;
                background: #e9ecef;
                border-radius: 5px;
            }}

            .view-link {{
                color: #4B3B8C;
                text-decoration: none;
            }}

            ul {{
                margin: 0;
                padding-left: 18px;
            }}
        </style>
    </head>
    <body>
        <img src="file:///{logo_path}" class="watermark" alt="Watermark Logo">
        <img src="file:///{logo_path}" class="header-logo" alt="Logo">

        <div class="container">
            <h1>Tender Overview: {tender.title or 'Untitled Tender'}</h1>

            <div class="section-group">
                <h2>Basic Information</h2>
                <table>
                    <tr><td class="label">Tender Number</td><td>{tender.tender_number or 'Not specified'}</td></tr>
                    <tr><td class="label">Issuing Organization</td><td>{format_text_for_table(tender.organization_details or 'Not specified')}</td></tr>
                </table>
            </div>

            <div class="section-group">
                <h2>Critical Dates</h2>
                <table>
                    <tr><td class="label">Due Date</td><td>{tender.due_date or 'Not specified'}</td></tr>
                    <tr><td class="label">Bid Opening Date</td><td>{tender.bid_opening_date or 'Not specified'}</td></tr>
                    <tr><td class="label">Bid Offer Validity</td><td>{tender.bid_offer_validity or 'Not specified'}</td></tr>
                    <tr><td class="label">Pre-bid Questions Deadline</td><td>{format_text_for_table(tender.question_deadline or 'Not specified')}</td></tr>
                </table>
            </div>

            <div class="section-group">
                <h2>Product & Delivery Details</h2>
                <table>
                    <thead>
                        <tr>
                            <th>Product</th>
                            <th>Quantity</th>
                            <th>Delivery Days</th>
                            <th>Consignee Reporting/Officer</th>
                            <th>Delivery Address</th>
                            <th>Specification Link</th>
                        </tr>
                    </thead>
                    <tbody>
                        {product_rows}
                    </tbody>
                </table>
            </div>

            <div class="section-group">
                <h2>Financial Requirements</h2>
                <table>
                    <tr><td class="label">EMD Amount</td><td>{format_text_for_table(tender.emd_amount or 'Not specified')}</td></tr>
                    <tr><td class="label">Estimated Cost</td><td>{format_text_for_table(tender.estimated_cost or 'Not specified')}</td></tr>
                    <tr><td class="label">Performance Security</td><td>{format_text_for_table(tender.performance_security or 'Not specified')}</td></tr>
                    <tr><td class="label">Payment Terms</td><td>{format_text_for_table(tender.payment_terms or 'Not specified')}</td></tr>
                </table>
            </div>

            <div class="section-group">
                <h2>Technical Requirements</h2>
                <table>
                    <tr><td class="label">Technical Specifications</td><td>{format_text_for_table(tender.technical_specifications or 'Not specified')}</td></tr>
                    <tr><td class="label">Scope of Work</td><td>{format_text_for_table(tender.scope_of_work or 'Not specified')}</td></tr>
                    <tr><td class="label">Performance Standards</td><td>{format_text_for_table(tender.performance_standards or 'Not specified')}</td></tr>
                </table>
            </div>

            <div class="section-group">
                <h2>Qualification & Evaluation</h2>
                <table>
                    <tr><td class="label">Qualification Criteria</td><td>{format_text_for_table(tender.qualification_criteria or 'Not specified')}</td></tr>
                    <tr><td class="label">Evaluation Criteria</td><td>{format_text_for_table(tender.evaluation_criteria or 'Not specified')}</td></tr>
                </table>
            </div>

            <div class="section-group">
                <h2>Special Provisions</h2>
                <table>
                    <tr><td class="label">Reverse Auction</td><td>{format_text_for_table(tender.reverse_auction or 'Not specified')}</td></tr>
                    <tr><td class="label">MSME Preferences</td><td>{format_text_for_table(tender.msme_preferences or 'Not specified')}</td></tr>
                    <tr><td class="label">Border Country Clause</td><td>{format_text_for_table(tender.border_country_clause or 'Not specified')}</td></tr>
                </table>
            </div>

            <div class="section-group">
                <h2>Compliance</h2>
                <table>
                    <tr><td class="label">Rejection Criteria</td><td>{format_text_for_table(tender.rejection_criteria or 'Not specified')}</td></tr>
                    <tr><td class="label">Documentation Requirements</td><td>{format_text_for_table(tender.documentation_requirements or 'Not specified')}</td></tr>
                </table>
            </div>

            <div class="section-group">
                <h2>Additional Details</h2>
                <table>
                    <tr><td>{format_text_for_table(additional_details_html)}</td></tr>
                </table>
            </div>

            <div class="section-group">
                <h2>Documents</h2>
                <table>
                    <tr>
                        <td class="label">Files</td>
                        <td>
                            <ul>
                                {documents_html}
                            </ul>
                        </td>
                    </tr>
                </table>
            </div>

            <div class="footer-box">
                <p style="margin:0; font-size:0.9em; color:#6c757d;">
                    This overview was generated using AI-powered document analysis.
                </p>
            </div>
        </div>
    </body>
    </html>
    """

    return re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', html_body)


def generate_tender_pdf_bytes(tender, products, documents, logo_path):
    """
    Generate PDF as BytesIO object from tender data.
    """
    html_body = build_tender_html(
        tender=tender,
        products=products,
        documents=documents,
        logo_path=logo_path
    )
    pdf_file = io.BytesIO()
    HTML(string=html_body).write_pdf(pdf_file)
    pdf_file.seek(0)
    return pdf_file