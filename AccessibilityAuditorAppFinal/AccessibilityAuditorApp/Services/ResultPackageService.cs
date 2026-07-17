using System.IO.Compression;
using AccessibilityAuditorApp.Models;

namespace AccessibilityAuditorApp.Services;

public class ResultPackageService
{
    public async Task<string> CreatePackageAsync(
        UploadJobResult job,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(job.EditedPdfPath) || !File.Exists(job.EditedPdfPath))
            throw new FileNotFoundException("Edited PDF was not found.", job.EditedPdfPath);

        if (string.IsNullOrWhiteSpace(job.SummaryTextPath) || !File.Exists(job.SummaryTextPath))
            throw new FileNotFoundException("Accessibility summary was not found.", job.SummaryTextPath);

        var zipPath = Path.Combine(job.JobFolder, GetPackageFileName(job));

        await using var zipFileStream = new FileStream(
            zipPath,
            FileMode.Create,
            FileAccess.ReadWrite,
            FileShare.None,
            bufferSize: 81920,
            useAsync: true
        );

        using (var archive = new ZipArchive(zipFileStream, ZipArchiveMode.Create, leaveOpen: true))
        {
            await AddFileAsync(
                archive,
                job.EditedPdfPath,
                GetEditedPdfFileName(job),
                cancellationToken
            );

            await AddFileAsync(
                archive,
                job.SummaryTextPath,
                "accessibility_remediation_summary.txt",
                cancellationToken
            );
        }

        await zipFileStream.FlushAsync(cancellationToken);

        job.ResultsZipPath = zipPath;
        return zipPath;
    }

    public string GetPackageFileName(UploadJobResult job)
    {
        var stem = GetSafeStem(job.OriginalPdfFileName);
        return $"{stem}_accessibility_results.zip";
    }

    private static string GetEditedPdfFileName(UploadJobResult job)
    {
        var stem = GetSafeStem(job.OriginalPdfFileName);
        return $"{stem}_remediated.pdf";
    }

    private static async Task AddFileAsync(
        ZipArchive archive,
        string sourcePath,
        string entryName,
        CancellationToken cancellationToken)
    {
        var entry = archive.CreateEntry(entryName, CompressionLevel.NoCompression);

        await using var input = new FileStream(
            sourcePath,
            FileMode.Open,
            FileAccess.Read,
            FileShare.Read,
            bufferSize: 81920,
            useAsync: true
        );

        await using var output = entry.Open();
        await input.CopyToAsync(output, cancellationToken);
    }

    private static string GetSafeStem(string originalFileName)
    {
        var stem = Path.GetFileNameWithoutExtension(originalFileName);

        if (string.IsNullOrWhiteSpace(stem))
            stem = "remediated_document";

        foreach (var invalidCharacter in Path.GetInvalidFileNameChars())
            stem = stem.Replace(invalidCharacter, '_');

        stem = stem.Trim();

        if (stem.Length > 80)
            stem = stem[..80];

        return stem;
    }
}
