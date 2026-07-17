using AccessibilityAuditorApp;
using AccessibilityAuditorApp.Components;
using AccessibilityAuditorApp.Services;
using Microsoft.AspNetCore.HttpOverrides;
using System.Net;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddRazorComponents()
    .AddInteractiveServerComponents();

builder.Services.AddHttpClient();

builder.Services.AddSingleton<JobStorageService>();
builder.Services.AddScoped<PythonEngineService>();
builder.Services.AddScoped<PdfEditingService>();
builder.Services.AddScoped<ResultPackageService>();
builder.Services.AddHostedService<TemporaryJobCleanupService>();

builder.Services.AddHsts(options =>
{
    options.MaxAge = TimeSpan.FromDays(365);
});

var pathBase = builder.Configuration.GetValue<string>(WebConstants.WebBasePathSettingsName) ?? "/";
var knownProxyIp = builder.Configuration["ReverseProxy:KnownProxyIp"]?.Trim();
var trustedProxyConfigured = !IsMissingOrPlaceholder(knownProxyIp);

if (trustedProxyConfigured)
{
    if (!IPAddress.TryParse(knownProxyIp, out var trustedProxy))
        throw new InvalidOperationException("ReverseProxy:KnownProxyIp must be a valid IP address or left blank.");

    builder.Services.Configure<ForwardedHeadersOptions>(options =>
    {
        options.ForwardedHeaders =
            ForwardedHeaders.XForwardedFor |
            ForwardedHeaders.XForwardedProto;
        options.KnownProxies.Add(trustedProxy);
    });
}

if (!builder.Environment.IsDevelopment())
{
    ValidateProductionConfiguration(builder.Configuration, pathBase);
}

var app = builder.Build();

if (trustedProxyConfigured)
    app.UseForwardedHeaders();

if (!app.Environment.IsDevelopment())
{
    app.UseExceptionHandler("/Error", createScopeForErrors: true);
    app.UseHsts();
}

if (!string.IsNullOrWhiteSpace(pathBase) && pathBase != "/")
{
    app.UsePathBase(pathBase);
}

//app.UseStatusCodePagesWithReExecute("/not-found", createScopeForStatusCodePages: true);
app.UseHttpsRedirection();

app.UseStaticFiles();
//app.MapStaticAssets();

app.UseRouting();
app.UseAntiforgery();

app.MapRazorComponents<App>()
    .AddInteractiveServerRenderMode();

app.Run();

static void ValidateProductionConfiguration(IConfiguration configuration, string pathBase)
{
    var backendUrl = configuration["AccessibilityBackend:BaseUrl"];
    if (IsMissingOrPlaceholder(backendUrl) ||
        !Uri.TryCreate(backendUrl, UriKind.Absolute, out var parsedBackendUrl) ||
        (parsedBackendUrl.Scheme != Uri.UriSchemeHttp && parsedBackendUrl.Scheme != Uri.UriSchemeHttps))
    {
        throw new InvalidOperationException(
            "AccessibilityBackend:BaseUrl must be set to an absolute HTTP or HTTPS URL in appsettings.Production.json.");
    }

    var apiKey = configuration["AccessibilityBackend:ApiKey"];
    if (IsMissingOrPlaceholder(apiKey) || apiKey!.Length < 32)
    {
        throw new InvalidOperationException(
            "AccessibilityBackend:ApiKey must be replaced in appsettings.Production.json with the shared production key.");
    }

    var allowedHosts = configuration["AllowedHosts"];
    if (IsMissingOrPlaceholder(allowedHosts) || allowedHosts == "*")
    {
        throw new InvalidOperationException(
            "AllowedHosts must be replaced with the production hostname in appsettings.Production.json.");
    }

    if (string.IsNullOrWhiteSpace(pathBase) || !pathBase.StartsWith('/'))
    {
        throw new InvalidOperationException("WebBasePath must begin with '/'.");
    }
}

static bool IsMissingOrPlaceholder(string? value)
{
    return string.IsNullOrWhiteSpace(value) ||
           value.Contains("REPLACE_WITH", StringComparison.OrdinalIgnoreCase);
}
