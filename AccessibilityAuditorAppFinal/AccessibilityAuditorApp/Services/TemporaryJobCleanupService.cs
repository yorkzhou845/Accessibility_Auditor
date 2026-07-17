namespace AccessibilityAuditorApp.Services;

/// <summary>
/// Fail-safe cleanup for orphaned temporary folders left by an abrupt process
/// termination. Normal jobs are deleted immediately by the page's finally block.
/// </summary>
public sealed class TemporaryJobCleanupService : BackgroundService
{
    private readonly TimeSpan _maximumAge;
    private readonly TimeSpan _cleanupInterval;
    private readonly JobStorageService _jobStorageService;
    private readonly ILogger<TemporaryJobCleanupService> _logger;

    public TemporaryJobCleanupService(
        IConfiguration configuration,
        JobStorageService jobStorageService,
        ILogger<TemporaryJobCleanupService> logger)
    {
        _jobStorageService = jobStorageService;
        _logger = logger;

        var maximumAgeMinutes = Math.Clamp(
            configuration.GetValue<int?>("TemporaryStorage:MaximumJobAgeMinutes") ?? 120,
            15,
            1440
        );

        var cleanupIntervalMinutes = Math.Clamp(
            configuration.GetValue<int?>("TemporaryStorage:CleanupIntervalMinutes") ?? 15,
            5,
            240
        );

        _maximumAge = TimeSpan.FromMinutes(maximumAgeMinutes);
        _cleanupInterval = TimeSpan.FromMinutes(cleanupIntervalMinutes);
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        DeleteExpiredFolders();

        using var timer = new PeriodicTimer(_cleanupInterval);

        try
        {
            while (await timer.WaitForNextTickAsync(stoppingToken))
                DeleteExpiredFolders();
        }
        catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
        {
            // Normal application shutdown.
        }
    }

    private void DeleteExpiredFolders()
    {
        try
        {
            if (!Directory.Exists(_jobStorageService.JobsRoot))
                return;

            var cutoff = DateTime.UtcNow - _maximumAge;

            foreach (var directory in Directory.EnumerateDirectories(_jobStorageService.JobsRoot))
            {
                try
                {
                    if (Directory.GetLastWriteTimeUtc(directory) < cutoff)
                        Directory.Delete(directory, recursive: true);
                }
                catch (IOException)
                {
                    // A live job may still be using the directory. Retry later.
                }
                catch (UnauthorizedAccessException ex)
                {
                    _logger.LogWarning(ex, "Could not delete orphaned temporary folder {Directory}.", directory);
                }
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Temporary job cleanup failed.");
        }
    }
}
