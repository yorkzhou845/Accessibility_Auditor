using AccessibilityAuditorApp.Models;
using Microsoft.AspNetCore.Components.Forms;

namespace AccessibilityAuditorApp.Services;

public class JobStorageService
{
    private static readonly HashSet<string> AllowedTasks = new(StringComparer.OrdinalIgnoreCase)
    {
        "table_summary",
        "alt_text"
    };

    private readonly ILogger<JobStorageService> _logger;

    public string JobsRoot { get; }

    public JobStorageService(
        IConfiguration configuration,
        ILogger<JobStorageService> logger)
    {
        _logger = logger;

        var configuredRoot = configuration["TemporaryStorage:JobsRoot"]?.Trim();
        var defaultRoot = Path.Combine(
            Path.GetTempPath(),
            "AccessibilityAuditorApp",
            "Jobs"
        );

        JobsRoot = Path.GetFullPath(
            string.IsNullOrWhiteSpace(configuredRoot)
                ? defaultRoot
                : Environment.ExpandEnvironmentVariables(configuredRoot)
        );

        Directory.CreateDirectory(JobsRoot);
    }

    public async Task<UploadJobResult> SaveUploadAsync(
        IBrowserFile pdfFile,
        IReadOnlyCollection<string> selectedTasks,
        string selectedTaskDisplayName,
        CancellationToken cancellationToken = default)
    {
        if (pdfFile is null)
            throw new InvalidOperationException("PDF file is required.");

        if (!pdfFile.Name.EndsWith(".pdf", StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("The uploaded file must be a PDF.");

        var normalizedTasks = selectedTasks
            .Where(task => !string.IsNullOrWhiteSpace(task))
            .Select(task => task.Trim())
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        if (normalizedTasks.Count == 0)
            throw new InvalidOperationException("Please select image captioning, table summarization, or both.");

        if (normalizedTasks.Any(task => !AllowedTasks.Contains(task)))
            throw new InvalidOperationException("Only Image Captioning and Table Summarization are supported.");

        var jobId = $"{DateTime.UtcNow:yyyyMMdd_HHmmss}_{Guid.NewGuid():N}";
        var jobFolder = Path.Combine(JobsRoot, jobId);
        var pdfPath = Path.Combine(jobFolder, "input.pdf");

        Directory.CreateDirectory(jobFolder);

        try
        {
            const long maxFileSize = 100 * 1024 * 1024; // 100 MB

            if (pdfFile.Size <= 0)
                throw new InvalidOperationException("The selected PDF is empty. Please select the file again.");

            await using (var uploadedPdfStream = pdfFile.OpenReadStream(maxFileSize, cancellationToken))
            await using (var pdfStream = new FileStream(
                pdfPath,
                FileMode.Create,
                FileAccess.Write,
                FileShare.None,
                bufferSize: 81920,
                useAsync: true))
            {
                await uploadedPdfStream.CopyToAsync(pdfStream, cancellationToken);
                await pdfStream.FlushAsync(cancellationToken);
            }

            var savedFileSize = new FileInfo(pdfPath).Length;

            if (savedFileSize <= 0)
                throw new InvalidOperationException("The PDF could not be copied into temporary processing storage.");

            await using (var signatureStream = File.OpenRead(pdfPath))
            {
                var signature = new byte[5];
                var bytesRead = await signatureStream.ReadAsync(signature, cancellationToken);
                var header = System.Text.Encoding.ASCII.GetString(signature, 0, bytesRead);

                if (!header.StartsWith("%PDF-", StringComparison.Ordinal))
                    throw new InvalidOperationException("The uploaded file is not a valid PDF document.");
            }

            return new UploadJobResult
            {
                JobId = jobId,
                JobFolder = jobFolder,
                OriginalPdfFileName = Path.GetFileName(pdfFile.Name),
                PdfPath = pdfPath,
                SelectedTasks = normalizedTasks,
                SelectedTaskDisplayName = selectedTaskDisplayName,
                Status = "Uploaded",
                Messages =
                {
                    "PDF uploaded to a temporary processing folder.",
                    $"Selected task(s): {selectedTaskDisplayName}."
                }
            };
        }
        catch
        {
            DeleteJobFolder(jobFolder);
            throw;
        }
    }

    public void DeleteJobFolder(UploadJobResult? job)
    {
        if (job is null)
            return;

        DeleteJobFolder(job.JobFolder);
    }

    private void DeleteJobFolder(string jobFolder)
    {
        if (string.IsNullOrWhiteSpace(jobFolder))
            return;

        try
        {
            var jobsRootFullPath = Path.GetFullPath(JobsRoot)
                .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
                + Path.DirectorySeparatorChar;

            var jobFolderFullPath = Path.GetFullPath(jobFolder);

            if (!jobFolderFullPath.StartsWith(jobsRootFullPath, StringComparison.OrdinalIgnoreCase))
            {
                _logger.LogWarning("Refused to delete a folder outside the temporary jobs root: {JobFolder}", jobFolder);
                return;
            }

            if (Directory.Exists(jobFolderFullPath))
                Directory.Delete(jobFolderFullPath, recursive: true);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Could not delete temporary job folder {JobFolder}.", jobFolder);
        }
    }
}
