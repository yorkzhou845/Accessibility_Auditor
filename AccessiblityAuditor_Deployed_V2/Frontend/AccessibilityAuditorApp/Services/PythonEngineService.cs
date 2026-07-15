using System.Net.Http.Headers;
using System.Text.Json;
using System.Text.Json.Serialization;
using AccessibilityAuditorApp.Models;

namespace AccessibilityAuditorApp.Services;

/// <summary>
/// Calls the FastAPI remediation backend running on the same local machine.
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
            Environment.GetEnvironmentVariable("ACCESSIBILITY_BACKEND_BASE_URL"),
            _configuration["AccessibilityBackend:BaseUrl"]
        );

        if (string.IsNullOrWhiteSpace(baseUrl))
            throw new InvalidOperationException("Set AccessibilityBackend:BaseUrl or ACCESSIBILITY_BACKEND_BASE_URL.");

        if (!File.Exists(job.PdfPath))
            throw new FileNotFoundException("Uploaded PDF was not found.", job.PdfPath);

        var pdfBytes = await File.ReadAllBytesAsync(job.PdfPath, cancellationToken);
        if (pdfBytes.Length == 0)
            throw new InvalidOperationException("The temporary PDF is empty.");

        if (job.SelectedTasks.Count == 0)
            throw new InvalidOperationException("No remediation task was selected.");

        var engineOutputFolder = Path.Combine(job.JobFolder, "engine_output");
        Directory.CreateDirectory(engineOutputFolder);
        var resultsJsonPath = Path.Combine(engineOutputFolder, "all_results.json");

        job.Status = "Processing";
        job.EngineOutputFolder = engineOutputFolder;
        job.ResultsJsonPath = resultsJsonPath;
        job.Messages.Add($"Sending PDF to the local remediation backend for: {job.SelectedTaskDisplayName}.");

        var endpoint = BuildEndpoint(baseUrl, "remediate");
        using var request = new HttpRequestMessage(HttpMethod.Post, endpoint);
        using var form = new MultipartFormDataContent();
        using var pdfContent = new ByteArrayContent(pdfBytes);

        pdfContent.Headers.ContentType = new MediaTypeHeaderValue("application/pdf");
        pdfContent.Headers.ContentLength = pdfBytes.LongLength;
        form.Add(pdfContent, "pdf", Path.GetFileName(job.PdfPath));

        var selectedTasks = string.Join(",", job.SelectedTasks);
        form.Add(new StringContent(selectedTasks), "tasks");
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
            job.Messages.Add("The local remediation backend request timed out.");
            job.EngineStandardError = ex.Message;
            return job;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Could not reach the local remediation backend.");
            job.Status = "Engine failed";
            job.Messages.Add("Could not reach the local remediation backend. Confirm that FastAPI is running.");
            job.EngineStandardError = ex.Message;
            return job;
        }

        if (!response.IsSuccessStatusCode)
        {
            _logger.LogError("The local backend returned HTTP {StatusCode}.", (int)response.StatusCode);
            job.Status = "Engine failed";
            job.EngineExitCode = (int)response.StatusCode;
            job.EngineStandardError = responseBody;
            job.Messages.Add($"The local remediation backend returned HTTP {(int)response.StatusCode}.");
            return job;
        }

        EngineResponse? payload;
        try
        {
            payload = JsonSerializer.Deserialize<EngineResponse>(
                responseBody,
                new JsonSerializerOptions { PropertyNameCaseInsensitive = true }
            );
        }
        catch (JsonException ex)
        {
            _logger.LogError(ex, "The local backend returned invalid JSON.");
            job.Status = "Engine failed";
            job.Messages.Add("The local remediation backend returned invalid JSON.");
            job.EngineStandardError = ex.Message;
            return job;
        }

        if (payload is null)
        {
            job.Status = "Engine failed";
            job.Messages.Add("The local remediation backend returned an empty response.");
            return job;
        }

        job.EngineStandardOutput = payload.Stdout ?? "";
        job.EngineStandardError = payload.Stderr ?? "";
        job.EngineExitCode = payload.ExitCode;

        if (!payload.Success)
        {
            _logger.LogError("The local backend reported failure: {Error}", payload.Error);
            job.Status = "Engine failed";
            job.Messages.Add(payload.Error ?? "The local remediation backend reported failure.");
            return job;
        }

        if (string.IsNullOrWhiteSpace(payload.ResultJson))
        {
            job.Status = "Engine failed";
            job.Messages.Add("The local remediation backend completed without results JSON.");
            return job;
        }

        await File.WriteAllTextAsync(resultsJsonPath, payload.ResultJson, cancellationToken);
        job.Status = "Engine complete";
        job.Messages.Add("Local remediation completed successfully.");
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

    private sealed class EngineResponse
    {
        [JsonPropertyName("success")]
        public bool Success { get; set; }

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
