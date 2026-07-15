def get_failure_report_path(pdf_path):
    """
    Finds the failure report that matches a PDF.

    Preferred naming:
        Example.pdf
        Example_Failure_Report.txt
    """

    exact_path = pdf_path.with_name(f"{pdf_path.stem}_Failure_Report.txt")

    if exact_path.exists():
        return exact_path

    # Fallback: allow names like Example_Failure_Report(1).txt
    possible_reports = sorted(
        pdf_path.parent.glob(f"{pdf_path.stem}*Failure*Report*.txt")
    )

    if possible_reports:
        return possible_reports[0]

    return None
