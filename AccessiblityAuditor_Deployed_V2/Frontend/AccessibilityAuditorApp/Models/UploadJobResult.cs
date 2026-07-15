namespace AccessibilityAuditorApp.Models;

public class UploadJobResult
{
    public string JobId { get; set; } = "";
    public string JobFolder { get; set; } = "";
    public string OriginalPdfFileName { get; set; } = "";
    public string PdfPath { get; set; } = "";
    public string Status { get; set; } = "Uploaded";
    public List<string> SelectedTasks { get; set; } = new();
    public string SelectedTaskDisplayName { get; set; } = "";
    public List<string> Messages { get; set; } = new();

    public string EngineOutputFolder { get; set; } = "";
    public string ResultsJsonPath { get; set; } = "";
    public int? EngineExitCode { get; set; }
    public string EngineStandardOutput { get; set; } = "";
    public string EngineStandardError { get; set; } = "";
    public string EditedPdfPath { get; set; } = "";
    public string SummaryTextPath { get; set; } = "";
    public string ResultsZipPath { get; set; } = "";
    public bool EditedPdfCreated { get; set; }
}
