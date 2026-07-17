using System.Net.Http.Headers;
using System.Text.Json;
using System.Text.Json.Serialization;
using AccessibilityAuditorApp.Models;

namespace AccessibilityAuditorApp.Services;

/// <summary>
/// Calls the GB10-hosted Python/FastAPI remediation backend.
/// The Blazor app no longer starts Python locally.
/// </summary>
public class PythonEngineService
{
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly IConfiguration _configuration;
    private readonly ILogger<PythonEngineService> _logger;

    public PythonEngineService(
        IHttpClientFactory httpClientFactory,
        IConfiguration configuration,
        ILogger<PythonEngineService> logger)
    {
        _httpClientFactory = httpClientFactory;
        _configuration = configuration;
        _logger = logger;
    }

    public async Task<UploadJobResult> RunAsync(
        UploadJobResult job,
        CancellationToken cancellationToken = default)
    {
        var baseUrl = FirstNonEmpty(
            _configuration["AccessibilityBackend:BaseUrl"],
            Environment.GetEnvironmentVariable("ACCESSIBILITY_BACKEND_BASE_URL")
        );

        if (string.IsNullOrWhiteSpace(baseUrl))
            throw new InvalidOperationException("AccessibilityBackend:BaseUrl is missing.");

        var apiKey = FirstNonEmpty(
            _configuration["AccessibilityBackend:ApiKey"],
            Environment.GetEnvironmentVariable("ACCESSIBILITY_BACKEND_API_KEY")
        );

        if (string.IsNullOrWhiteSpace(apiKey))
            throw new InvalidOperationException("AccessibilityBackend:ApiKey is missing.");

        if (!File.Exists(job.PdfPath))
            throw new FileNotFoundException("Uploaded PDF was not found.", job.PdfPath);

        var pdfBytes = await File.ReadAllBytesAsync(job.PdfPath, cancellationToken);

        if (pdfBytes.Length == 0)
            throw new InvalidOperationException("The temporary PDF is empty and cannot be sent to GB10.");

        if (job.SelectedTasks.Count == 0)
            throw new InvalidOperationException("No remediation task was selected.");

        var engineOutputFolder = Path.Combine(job.JobFolder, "engine_output");
        Directory.CreateDirectory(engineOutputFolder);

        var resultsJsonPath = Path.Combine(engineOutputFolder, "all_results.json");

        job.Status = "Processing";
        job.EngineOutputFolder = engineOutputFolder;
        job.ResultsJsonPath = resultsJsonPath;
        job.Messages.Add($"Sending PDF to the GB10 remediation backend for task(s): {job.SelectedTaskDisplayName}.");

        var endpoint = BuildEndpoint(baseUrl, "remediate");
        using var request = new HttpRequestMessage(HttpMethod.Post, endpoint);
        request.Headers.Add("X-API-KEY", apiKey);

        using var form = new MultipartFormDataContent();

        // Send a fixed byte buffer so the multipart request cannot begin from an
        // unexpected stream position or arrive at GB10 as a zero-byte file.
        var pdfContent = new ByteArrayContent(pdfBytes);
        pdfContent.Headers.ContentType = new MediaTypeHeaderValue("application/pdf");
        pdfContent.Headers.ContentLength = pdfBytes.LongLength;
        form.Add(pdfContent, "pdf", Path.GetFileName(job.PdfPath));

        var selectedTasks = string.Join(",", job.SelectedTasks);
        form.Add(new StringContent(selectedTasks), "tasks");
        form.Add(new StringContent(selectedTasks), "task");

        request.Content = form;

        var requestTimeoutMinutes = Math.Clamp(
            _configuration.GetValue<int?>("AccessibilityBackend:RequestTimeoutMinutes") ?? 30,
            1,
            180
        );

        var client = _httpClientFactory.CreateClient();
        client.Timeout = TimeSpan.FromMinutes(requestTimeoutMinutes);

        HttpResponseMessage response;
        string responseBody;

        try
        {
            response = await client.SendAsync(request, cancellationToken);
            responseBody = await response.Content.ReadAsStringAsync(cancellationToken);
        }
        catch (TaskCanceledException ex) when (!cancellationToken.IsCancellationRequested)
        {
            job.Status = "Engine failed";
            job.Messages.Add("The GB10 remediation backend request timed out.");
            job.EngineStandardError = ex.Message;
            return job;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Could not reach the GB10 remediation backend.");

            job.Status = "Engine failed";
            job.Messages.Add("Could not reach the GB10 remediation backend.");
            job.EngineStandardError = ex.Message;
            return job;
        }

        if (!response.IsSuccessStatusCode)
        {
            _logger.LogError(
                "The GB10 backend returned HTTP {StatusCode}. Response: {ResponseBody}",
                (int)response.StatusCode,
                responseBody
            );

            job.Status = "Engine failed";
            job.EngineExitCode = (int)response.StatusCode;
            job.EngineStandardError = responseBody;
            job.Messages.Add($"The GB10 remediation backend returned HTTP {(int)response.StatusCode}.");

            return job;
        }

        RemoteEngineResponse? payload;

        try
        {
            payload = JsonSerializer.Deserialize<RemoteEngineResponse>(
                responseBody,
                new JsonSerializerOptions
                {
                    PropertyNameCaseInsensitive = true
                });
        }
        catch (JsonException ex)
        {
            _logger.LogError(ex, "The GB10 backend returned invalid JSON. Response: {ResponseBody}", responseBody);
            job.Status = "Engine failed";
            job.Messages.Add("The GB10 remediation backend returned invalid JSON.");
            job.EngineStandardError = ex.Message + Environment.NewLine + responseBody;
            return job;
        }

        if (payload is null)
        {
            job.Status = "Engine failed";
            job.Messages.Add("The GB10 remediation backend returned an empty response.");
            job.EngineStandardError = responseBody;
            return job;
        }

        job.EngineStandardOutput = payload.Stdout ?? "";
        job.EngineStandardError = payload.Stderr ?? "";
        job.EngineExitCode = payload.ExitCode;

        if (!payload.Success)
        {
            _logger.LogError(
                "The GB10 backend reported failure. Error: {Error}. Standard error: {StandardError}",
                payload.Error,
                payload.Stderr
            );

            job.Status = "Engine failed";
            job.Messages.Add(payload.Error ?? "The GB10 remediation backend reported failure.");
            return job;
        }

        if (string.IsNullOrWhiteSpace(payload.ResultJson))
        {
            job.Status = "Engine failed";
            job.Messages.Add("The GB10 remediation backend completed, but returned no results JSON.");
            return job;
        }

        await File.WriteAllTextAsync(resultsJsonPath, payload.ResultJson, cancellationToken);

        job.Status = "Engine complete";
        job.Messages.Add("GB10 remediation backend completed successfully.");
        job.Messages.Add("JSON remediation result stored only in the temporary job folder for PDF editing.");

        return job;
    }

    private static Uri BuildEndpoint(string baseUrl, string relativePath)
    {
        var normalized = baseUrl.TrimEnd('/') + "/";
        return new Uri(new Uri(normalized), relativePath);
    }

    private static string FirstNonEmpty(params string?[] values)
    {
        foreach (var value in values)
        {
            if (!string.IsNullOrWhiteSpace(value))
                return value.Trim();
        }

        return "";
    }

    private sealed class RemoteEngineResponse
    {
        [JsonPropertyName("success")]
        public bool Success { get; set; }

        [JsonPropertyName("status")]
        public string? Status { get; set; }

        [JsonPropertyName("job_id")]
        public string? JobId { get; set; }

        [JsonPropertyName("exit_code")]
        public int? ExitCode { get; set; }

        [JsonPropertyName("stdout")]
        public string? Stdout { get; set; }

        [JsonPropertyName("stderr")]
        public string? Stderr { get; set; }

        [JsonPropertyName("result_json")]
        public string? ResultJson { get; set; }

        [JsonPropertyName("error")]
        public string? Error { get; set; }
    }
}
