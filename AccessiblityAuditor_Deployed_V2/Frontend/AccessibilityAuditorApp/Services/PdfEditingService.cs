using System.Text;
using System.Text.Json;
using AccessibilityAuditorApp.Models;
using iTextSharp.text.pdf;
using iTextSharp.text.pdf.parser;
using IOPath = System.IO.Path;

namespace AccessibilityAuditorApp.Services;

public class PdfEditingService
{
    private enum PdfRemediationMode
    {
        TaggedPdf,
        UntaggedPdf,
        Unknown
    }


    private sealed class ElementCoordinates
    {
        public int? X { get; set; }
        public int? Y { get; set; }
        public int? Width { get; set; }
        public int? Height { get; set; }

        public override string ToString()
        {
            if (X is null || Y is null || Width is null || Height is null)
                return "unknown";

            return $"x={X}, y={Y}, width={Width}, height={Height}";
        }
    }

    private sealed class AltTextInstruction
    {
        public int? PageNumber { get; set; }
        public List<string> TargetEntryIds { get; set; } = new();
        public ElementCoordinates? TargetCoordinates { get; set; }
        public string AltText { get; set; } = "";
        public bool? Decorative { get; set; }
        public bool? ImageContainsText { get; set; }
        public double? Confidence { get; set; }
    }

    private sealed class TableSummaryInstruction
    {
        public int? PageNumber { get; set; }
        public List<string> TargetEntryIds { get; set; } = new();
        public ElementCoordinates? TargetCoordinates { get; set; }
        public string Summary { get; set; } = "";
        public string SummaryAttribute { get; set; } = "";
        public string MarkdownTable { get; set; } = "";
        public double? Confidence { get; set; }
    }

    private sealed class AccessibleStructureElement
    {
        public PdfDictionary Dictionary { get; set; } = new();
        public string CurrentTag { get; set; } = "";
        public int? PageNumber { get; set; }
        public int Depth { get; set; }
        public string Path { get; set; } = "";
        public List<int> MarkedContentIds { get; set; } = new();
        public string ObjectKey { get; set; } = "";
    }

    private sealed class PdfRemediationInstructions
    {
        public List<AltTextInstruction> AltTexts { get; set; } = new();
        public List<TableSummaryInstruction> TableSummaries { get; set; } = new();
    }

    public Task<UploadJobResult> CreateEditedPdfAsync(UploadJobResult job)
    {
        if (string.IsNullOrWhiteSpace(job.PdfPath) || !File.Exists(job.PdfPath))
            throw new FileNotFoundException("Input PDF was not found.", job.PdfPath);

        if (string.IsNullOrWhiteSpace(job.ResultsJsonPath) || !File.Exists(job.ResultsJsonPath))
            throw new FileNotFoundException("Results JSON was not found.", job.ResultsJsonPath);

        var editedPdfPath = IOPath.Combine(job.JobFolder, "edited.pdf");

        var instructions = ReadRemediationInstructions(job.ResultsJsonPath);

        using var reader = new PdfReader(job.PdfPath);
        using var outputStream = new FileStream(editedPdfPath, FileMode.Create, FileAccess.Write);
        using var stamper = new PdfStamper(reader, outputStream);

        var remediationMode = DetermineRemediationMode(reader);
        AddModeMessages(job, remediationMode);

        ApplyAltTextInstructions(
            stamper,
            reader,
            instructions.AltTexts,
            remediationMode,
            job
        );

        ApplyTableSummaryInstructions(
            stamper,
            reader,
            instructions.TableSummaries,
            remediationMode,
            job
        );

        WriteRemediationSummary(
            job,
            instructions,
            remediationMode
        );

        UpdatePdfMetadata(
            stamper,
            reader,
            job,
            instructions,
            remediationMode
        );

        job.EditedPdfPath = editedPdfPath;
        job.EditedPdfCreated = File.Exists(editedPdfPath);

        if (job.EditedPdfCreated)
            job.Messages.Add("Edited PDF file created successfully.");

        return Task.FromResult(job);
    }

    private static PdfRemediationInstructions ReadRemediationInstructions(string resultsJsonPath)
    {
        var json = File.ReadAllText(resultsJsonPath);

        using var document = JsonDocument.Parse(json);
        var root = document.RootElement;

        var results = GetResultObjects(root);
        var instructions = new PdfRemediationInstructions();

        foreach (var result in results)
        {
            var pageNumber = GetNullableInt(result, "page_number");

            if (!result.TryGetProperty("remediations", out var remediations) ||
                remediations.ValueKind != JsonValueKind.Array)
            {
                continue;
            }

            foreach (var remediation in remediations.EnumerateArray())
            {
                if (!remediation.TryGetProperty("proposed_change", out var proposedChange))
                    continue;

                var actionType = GetString(proposedChange, "action_type");
                var confidence = GetNullableDouble(remediation, "confidence");

                if (string.Equals(actionType, "add_or_update_alt_text", StringComparison.OrdinalIgnoreCase))
                {
                    ReadAltTextInstruction(
                        remediation,
                        proposedChange,
                        pageNumber,
                        confidence,
                        instructions
                    );
                }
                else if (string.Equals(actionType, "add_table_summary", StringComparison.OrdinalIgnoreCase))
                {
                    ReadTableSummaryInstruction(
                        remediation,
                        proposedChange,
                        pageNumber,
                        confidence,
                        instructions
                    );
                }
            }
        }


        return instructions;
    }


    private static void ReadAltTextInstruction(
        JsonElement remediation,
        JsonElement proposedChange,
        int? pageNumber,
        double? confidence,
        PdfRemediationInstructions instructions)
    {
        var altText = GetString(proposedChange, "alt_text");
        var decorative = GetNullableBool(proposedChange, "decorative");
        var imageContainsText = GetNullableBool(proposedChange, "image_contains_text");

        // Keep the instruction even when the model returned empty/null alt text.
        // The apply step will skip it with a visible diagnostic message instead
        // of silently dropping the image from the remediation summary.
        instructions.AltTexts.Add(new AltTextInstruction
        {
            PageNumber = pageNumber,
            TargetEntryIds = GetStringArray(remediation, "target_entry_ids"),
            TargetCoordinates = GetCoordinates(remediation, "target_coordinates"),
            AltText = altText.Trim(),
            Decorative = decorative,
            ImageContainsText = imageContainsText,
            Confidence = confidence
        });
    }

    private static void ReadTableSummaryInstruction(
        JsonElement remediation,
        JsonElement proposedChange,
        int? pageNumber,
        double? confidence,
        PdfRemediationInstructions instructions)
    {
        var summary = GetString(proposedChange, "summary");
        var summaryAttribute = GetString(proposedChange, "summary_attribute");
        var markdownTable = GetString(proposedChange, "markdown_table");

        if (string.IsNullOrWhiteSpace(summary) &&
            string.IsNullOrWhiteSpace(summaryAttribute) &&
            string.IsNullOrWhiteSpace(markdownTable))
        {
            return;
        }

        instructions.TableSummaries.Add(new TableSummaryInstruction
        {
            PageNumber = pageNumber,
            TargetEntryIds = GetStringArray(remediation, "target_entry_ids"),
            TargetCoordinates = GetCoordinates(remediation, "target_coordinates"),
            Summary = summary.Trim(),
            SummaryAttribute = summaryAttribute.Trim(),
            MarkdownTable = markdownTable.Trim(),
            Confidence = confidence
        });
    }

    private static void ApplyAltTextInstructions(
        PdfStamper stamper,
        PdfReader reader,
        List<AltTextInstruction> altTexts,
        PdfRemediationMode remediationMode,
        UploadJobResult job)
    {
        if (altTexts.Count == 0)
        {
            job.Messages.Add("No alt-text instructions were found.");
            return;
        }

        if (remediationMode != PdfRemediationMode.TaggedPdf)
        {
            job.Messages.Add(
                $"PDF was not classified as fully tagged, but alt-text injection will still be attempted if /Figure structure elements exist."
            );
        }

        var figureElements = CollectAccessibleStructureElements(
            reader,
            new HashSet<string> { "/Figure" }
        );

        if (figureElements.Count == 0)
        {
            job.Messages.Add(
                $"Parsed {altTexts.Count} alt-text instruction(s), but no /Figure structure element was found for /Alt injection. The captions remain listed in the separate remediation summary file."
            );
            return;
        }

        var usedElements = new HashSet<string>();
        var appliedCount = 0;
        var skippedCount = 0;

        foreach (var instruction in altTexts)
        {
            if (instruction.Decorative != true && string.IsNullOrWhiteSpace(instruction.AltText))
            {
                skippedCount++;
                job.Messages.Add(
                    $"Alt-text injection skipped for page {instruction.PageNumber?.ToString() ?? "unknown"}: the generated alt text was empty or null for a non-decorative image. Target ids: {FormatTargetIds(instruction.TargetEntryIds)}. Coordinates: {instruction.TargetCoordinates?.ToString() ?? "unknown"}."
                );
                continue;
            }

            var match = SelectBestAccessibleElementMatch(
                figureElements,
                instruction.PageNumber,
                usedElements,
                allowSequentialFallback: true
            );

            if (match is null)
            {
                skippedCount++;
                job.Messages.Add(
                    $"Alt-text injection skipped for page {instruction.PageNumber?.ToString() ?? "unknown"}: no unused same-page /Figure structure element was found. Target ids: {FormatTargetIds(instruction.TargetEntryIds)}. Coordinates: {instruction.TargetCoordinates?.ToString() ?? "unknown"}."
                );
                continue;
            }

            var altValue = instruction.Decorative == true
                ? ""
                : instruction.AltText.Trim();

            match.Dictionary.Put(PdfName.ALT, MakePdfString(altValue));

            if (instruction.ImageContainsText == true && !string.IsNullOrWhiteSpace(instruction.AltText))
            {
                match.Dictionary.Put(PdfName.ACTUALTEXT, MakePdfString(instruction.AltText.Trim()));
            }

            stamper.MarkUsed(match.Dictionary);
            usedElements.Add(GetStableElementKey(match));
            appliedCount++;

            job.Messages.Add(
                $"Alt-text injection applied: page={match.PageNumber?.ToString() ?? "unknown"}, tag={match.CurrentTag}, object={match.ObjectKey}, path={match.Path}, decorative={instruction.Decorative?.ToString() ?? "unknown"}, alt=\"{TrimMessageText(altValue)}\"."
            );
        }

        job.Messages.Add(
            $"Alt-text processing completed. Applied {appliedCount} /Alt update(s); skipped {skippedCount}; parsed {altTexts.Count} instruction(s)."
        );
    }

    private static void ApplyTableSummaryInstructions(
        PdfStamper stamper,
        PdfReader reader,
        List<TableSummaryInstruction> tableSummaries,
        PdfRemediationMode remediationMode,
        UploadJobResult job)
    {
        if (tableSummaries.Count == 0)
        {
            job.Messages.Add("No table-summary instructions were found.");
            return;
        }

        if (remediationMode != PdfRemediationMode.TaggedPdf)
        {
            job.Messages.Add(
                $"Parsed {tableSummaries.Count} table-summary instruction(s), but skipped direct table structure updates because the PDF is not confirmed as tagged. The summaries remain listed in the separate remediation summary file."
            );
            return;
        }

        var tableElements = CollectAccessibleStructureElements(
            reader,
            new HashSet<string> { "/Table" }
        );

        if (tableElements.Count == 0)
        {
            job.Messages.Add(
                $"Parsed {tableSummaries.Count} table-summary instruction(s), but no /Table structure element was found. The summaries remain listed in the separate remediation summary file."
            );
            return;
        }

        var usedElements = new HashSet<string>();
        var appliedCount = 0;
        var skippedCount = 0;

        foreach (var instruction in tableSummaries)
        {
            var summaryText = FirstNonEmpty(
                instruction.Summary,
                instruction.SummaryAttribute,
                BuildPlainTextTableSummaryFallback(instruction.MarkdownTable)
            );

            if (string.IsNullOrWhiteSpace(summaryText))
            {
                skippedCount++;
                job.Messages.Add(
                    $"Table-summary injection skipped for page {instruction.PageNumber?.ToString() ?? "unknown"}: summary text was empty."
                );
                continue;
            }

            var match = SelectBestAccessibleElementMatch(
                tableElements,
                instruction.PageNumber,
                usedElements,
                allowSequentialFallback: true
            );

            if (match is null)
            {
                skippedCount++;
                job.Messages.Add(
                    $"Table-summary injection skipped for page {instruction.PageNumber?.ToString() ?? "unknown"}: no unused same-page /Table structure element was found. Target ids: {FormatTargetIds(instruction.TargetEntryIds)}. Coordinates: {instruction.TargetCoordinates?.ToString() ?? "unknown"}."
                );
                continue;
            }

            ApplySummaryToTableElement(match.Dictionary, summaryText, stamper);
            stamper.MarkUsed(match.Dictionary);
            usedElements.Add(GetStableElementKey(match));
            appliedCount++;

            job.Messages.Add(
                $"Table-summary injection applied: page={match.PageNumber?.ToString() ?? "unknown"}, object={match.ObjectKey}, path={match.Path}, summary=\"{TrimMessageText(summaryText)}\"."
            );
        }

        job.Messages.Add(
            $"Table-summary processing completed. Applied {appliedCount} table structure update(s); skipped {skippedCount}; parsed {tableSummaries.Count} instruction(s)."
        );
    }

    private static List<AccessibleStructureElement> CollectAccessibleStructureElements(
        PdfReader reader,
        HashSet<string> targetStructureTypes)
    {
        var elements = new List<AccessibleStructureElement>();
        var pageReferenceMap = BuildPageReferenceMap(reader);

        var catalog = reader.Catalog;
        var structTreeRoot = catalog.GetAsDict(PdfName.STRUCTTREEROOT);

        if (structTreeRoot is null)
            return elements;

        var kids = structTreeRoot.Get(PdfName.K);

        if (kids is null)
            return elements;

        TraverseForAccessibleStructureElements(
            kids,
            elements,
            new HashSet<string>(),
            pageReferenceMap,
            targetStructureTypes,
            inheritedPageNumber: null,
            depth: 0,
            path: ""
        );

        return elements
            .OrderBy(e => e.PageNumber ?? int.MaxValue)
            .ThenBy(e => e.Depth)
            .ThenBy(e => e.Path)
            .ToList();
    }

    private static void TraverseForAccessibleStructureElements(
        PdfObject item,
        List<AccessibleStructureElement> elements,
        HashSet<string> visitedObjects,
        Dictionary<string, int> pageReferenceMap,
        HashSet<string> targetStructureTypes,
        int? inheritedPageNumber,
        int depth,
        string path)
    {
        if (item is null)
            return;

        var resolved = PdfReader.GetPdfObject(item);

        if (resolved is PdfArray array)
        {
            for (var i = 0; i < array.Size; i++)
            {
                var childPath = string.IsNullOrWhiteSpace(path)
                    ? $"[{i}]"
                    : $"{path}[{i}]";

                TraverseForAccessibleStructureElements(
                    array.GetPdfObject(i),
                    elements,
                    visitedObjects,
                    pageReferenceMap,
                    targetStructureTypes,
                    inheritedPageNumber,
                    depth,
                    childPath
                );
            }

            return;
        }

        if (resolved is not PdfDictionary dict)
            return;

        var objectKey = GetObjectKey(item);

        if (!string.IsNullOrWhiteSpace(objectKey) && !visitedObjects.Add(objectKey))
            return;

        var structureType = dict.GetAsName(PdfName.S);
        var structureTypeText = structureType?.ToString() ?? "/Unknown";

        var pageNumber = inheritedPageNumber;

        var pageObject = dict.Get(PdfName.PG);
        if (pageObject is not null)
        {
            var pageKey = GetObjectKey(pageObject);

            if (!string.IsNullOrWhiteSpace(pageKey) &&
                pageReferenceMap.TryGetValue(pageKey, out var mappedPageNumber))
            {
                pageNumber = mappedPageNumber;
            }
        }

        var currentPath = string.IsNullOrWhiteSpace(path)
            ? structureTypeText
            : $"{path}/{structureTypeText.TrimStart('/')}";

        var kids = dict.Get(PdfName.K);

        if (targetStructureTypes.Contains(structureTypeText))
        {
            elements.Add(new AccessibleStructureElement
            {
                Dictionary = dict,
                CurrentTag = structureTypeText,
                PageNumber = pageNumber,
                Depth = depth,
                Path = currentPath,
                MarkedContentIds = ExtractMarkedContentIds(kids),
                ObjectKey = objectKey
            });
        }

        if (kids is null)
            return;

        TraverseForAccessibleStructureElements(
            kids,
            elements,
            visitedObjects,
            pageReferenceMap,
            targetStructureTypes,
            pageNumber,
            depth + 1,
            currentPath
        );
    }

    private static AccessibleStructureElement? SelectBestAccessibleElementMatch(
        List<AccessibleStructureElement> elements,
        int? pageNumber,
        HashSet<string> usedElements,
        bool allowSequentialFallback = false)
    {
        var unused = elements
            .Where(e => !usedElements.Contains(GetStableElementKey(e)))
            .ToList();

        if (unused.Count == 0)
            return null;

        if (pageNumber is not null)
        {
            var samePage = unused
                .Where(e => e.PageNumber == pageNumber)
                .OrderBy(e => e.Path)
                .ThenBy(e => e.Depth)
                .ToList();

            if (samePage.Count > 0)
                return samePage.First();

            if (!allowSequentialFallback)
                return null;

            var unknownPage = unused
                .Where(e => e.PageNumber is null)
                .OrderBy(e => e.Path)
                .ThenBy(e => e.Depth)
                .FirstOrDefault();

            if (unknownPage is not null)
                return unknownPage;
        }

        if (!allowSequentialFallback && pageNumber is not null)
            return null;

        return unused
            .OrderBy(e => e.PageNumber ?? int.MaxValue)
            .ThenBy(e => e.Path)
            .ThenBy(e => e.Depth)
            .FirstOrDefault();
    }

    private static string GetStableElementKey(AccessibleStructureElement element)
    {
        if (!string.IsNullOrWhiteSpace(element.ObjectKey))
            return element.ObjectKey;

        return $"{element.PageNumber?.ToString() ?? "unknown"}:{element.CurrentTag}:{element.Path}:mcid={string.Join(",", element.MarkedContentIds)}";
    }

    private static PdfString MakePdfString(string value)
    {
        return new PdfString(value ?? "", PdfObject.TEXT_UNICODE);
    }

    private static void ApplySummaryToTableElement(
        PdfDictionary tableDictionary,
        string summaryText,
        PdfStamper stamper)
    {
        var summaryName = new PdfName("Summary");
        var summaryString = MakePdfString(summaryText);

        // PAC exposes /Alt on the Table structure element in the same visible
        // property pane used for Figure alt text. Keep /Summary too for tools
        // that inspect table-specific metadata, but write the human-readable
        // summary to /Alt so the remediation is visible and discoverable.
        // Do not write /ActualText on /Table: /ActualText can cause assistive
        // technology to read only the summary instead of the actual table cells.
        tableDictionary.Put(PdfName.ALT, MakePdfString(summaryText));
        tableDictionary.Put(summaryName, summaryString);

        // Also preserve the summary in a table attribute dictionary where possible.
        var attributeObject = tableDictionary.Get(new PdfName("A"));
        var resolvedAttributeObject = PdfReader.GetPdfObject(attributeObject);

        if (resolvedAttributeObject is PdfDictionary attributeDictionary)
        {
            attributeDictionary.Put(summaryName, MakePdfString(summaryText));
            stamper.MarkUsed(attributeDictionary);
        }
        else if (resolvedAttributeObject is PdfArray attributeArray)
        {
            var newAttributeDictionary = new PdfDictionary();
            newAttributeDictionary.Put(new PdfName("O"), new PdfName("Table"));
            newAttributeDictionary.Put(summaryName, MakePdfString(summaryText));
            attributeArray.Add(newAttributeDictionary);
            stamper.MarkUsed(attributeArray);
        }
        else
        {
            var newAttributeDictionary = new PdfDictionary();
            newAttributeDictionary.Put(new PdfName("O"), new PdfName("Table"));
            newAttributeDictionary.Put(summaryName, MakePdfString(summaryText));
            tableDictionary.Put(new PdfName("A"), newAttributeDictionary);
        }
    }

    private static string FirstNonEmpty(params string[] values)
    {
        foreach (var value in values)
        {
            if (!string.IsNullOrWhiteSpace(value))
                return value.Trim();
        }

        return "";
    }

    private static string BuildPlainTextTableSummaryFallback(string markdownTable)
    {
        if (string.IsNullOrWhiteSpace(markdownTable))
            return "";

        var compact = NormalizeSpacing(markdownTable.Replace("|", " "));

        if (compact.Length <= 240)
            return compact;

        return compact[..240] + "...";
    }

    private static string FormatTargetIds(List<string> targetEntryIds)
    {
        if (targetEntryIds.Count == 0)
            return "none";

        return string.Join(", ", targetEntryIds);
    }

    private static List<string> GetStringArray(JsonElement element, string propertyName)
    {
        var values = new List<string>();

        if (!element.TryGetProperty(propertyName, out var array) ||
            array.ValueKind != JsonValueKind.Array)
        {
            return values;
        }

        foreach (var item in array.EnumerateArray())
        {
            var value = item.ValueKind == JsonValueKind.String
                ? item.GetString()
                : item.ToString();

            if (!string.IsNullOrWhiteSpace(value))
                values.Add(value.Trim());
        }

        return values;
    }

    private static ElementCoordinates? GetCoordinates(JsonElement element, string propertyName)
    {
        if (!element.TryGetProperty(propertyName, out var coordinates) ||
            coordinates.ValueKind != JsonValueKind.Object)
        {
            return null;
        }

        return new ElementCoordinates
        {
            X = GetNullableInt(coordinates, "x"),
            Y = GetNullableInt(coordinates, "y"),
            Width = GetNullableInt(coordinates, "width"),
            Height = GetNullableInt(coordinates, "height")
        };
    }

    private static List<JsonElement> GetResultObjects(JsonElement root)
    {
        var results = new List<JsonElement>();

        if (root.ValueKind == JsonValueKind.Object &&
            root.TryGetProperty("results", out var directResults) &&
            directResults.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in directResults.EnumerateArray())
                results.Add(item);

            return results;
        }

        if (root.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in root.EnumerateArray())
            {
                if (item.ValueKind == JsonValueKind.Object &&
                    item.TryGetProperty("results", out var nestedResults) &&
                    nestedResults.ValueKind == JsonValueKind.Array)
                {
                    foreach (var nestedItem in nestedResults.EnumerateArray())
                        results.Add(nestedItem);
                }
                else
                {
                    results.Add(item);
                }
            }
        }

        return results;
    }


    private static void WriteRemediationSummary(
        UploadJobResult job,
        PdfRemediationInstructions instructions,
        PdfRemediationMode remediationMode)
    {
        var summaryPath = IOPath.Combine(
            job.JobFolder,
            "accessibility_remediation_summary.txt"
        );

        var summaryText = BuildRemediationSummaryText(job, instructions, remediationMode);
        File.WriteAllText(summaryPath, summaryText, Encoding.UTF8);

        job.SummaryTextPath = summaryPath;
        job.Messages.Add("Created accessibility_remediation_summary.txt as a separate output file.");
    }

    private static string BuildRemediationSummaryText(
        UploadJobResult job,
        PdfRemediationInstructions instructions,
        PdfRemediationMode remediationMode)
    {
        var sb = new StringBuilder();

        sb.AppendLine("Accessibility Remediation Summary");
        sb.AppendLine("=================================");
        sb.AppendLine();
        sb.AppendLine($"Job ID: {job.JobId}");
        sb.AppendLine($"Input PDF: {job.OriginalPdfFileName}");
        sb.AppendLine($"Remediation mode: {remediationMode}");
        sb.AppendLine();

        sb.AppendLine();
        sb.AppendLine("Alt-Text Instructions");
        sb.AppendLine("---------------------");
        sb.AppendLine($"Count: {instructions.AltTexts.Count}");

        foreach (var alt in instructions.AltTexts)
        {
            sb.AppendLine($"- Page {alt.PageNumber?.ToString() ?? "unknown"}");
            sb.AppendLine($"  Target ids: {FormatTargetIds(alt.TargetEntryIds)}");
            sb.AppendLine($"  Target coordinates: {alt.TargetCoordinates?.ToString() ?? "unknown"}");
            sb.AppendLine($"  Decorative: {alt.Decorative?.ToString() ?? "unknown"}");
            sb.AppendLine($"  Image contains text: {alt.ImageContainsText?.ToString() ?? "unknown"}");
            sb.AppendLine($"  Confidence: {alt.Confidence?.ToString() ?? "unknown"}");
            sb.AppendLine($"  Alt text: {alt.AltText}");
        }

        sb.AppendLine();
        sb.AppendLine("Table Summary Instructions");
        sb.AppendLine("--------------------------");
        sb.AppendLine($"Count: {instructions.TableSummaries.Count}");

        foreach (var table in instructions.TableSummaries)
        {
            sb.AppendLine($"- Page {table.PageNumber?.ToString() ?? "unknown"}");
            sb.AppendLine($"  Target ids: {FormatTargetIds(table.TargetEntryIds)}");
            sb.AppendLine($"  Target coordinates: {table.TargetCoordinates?.ToString() ?? "unknown"}");
            sb.AppendLine($"  Confidence: {table.Confidence?.ToString() ?? "unknown"}");
            sb.AppendLine($"  Summary: {table.Summary}");
            sb.AppendLine($"  Summary attribute: {table.SummaryAttribute}");

            if (!string.IsNullOrWhiteSpace(table.MarkdownTable))
            {
                sb.AppendLine("  Markdown table:");
                sb.AppendLine(table.MarkdownTable);
            }
        }

        sb.AppendLine();
        sb.AppendLine("Implementation Status");
        sb.AppendLine("---------------------");
        sb.AppendLine("Alt text is injected into matching /Figure structure elements when the PDF is tagged and a same-page figure element can be matched.");
        sb.AppendLine("Table summaries are injected into matching /Table structure elements when the PDF is tagged and a same-page table element can be matched.");
        sb.AppendLine("For untagged PDFs or unmatched elements, generated captions and summaries remain listed in this summary file for human review.");

        return sb.ToString();
    }

    private static void UpdatePdfMetadata(
        PdfStamper stamper,
        PdfReader reader,
        UploadJobResult job,
        PdfRemediationInstructions instructions,
        PdfRemediationMode remediationMode)
    {
        var info = reader.Info ?? new Dictionary<string, string>();

        info["Producer"] = "AccessibilityAuditorApp using iTextSharp";
        info["AccessibilityAuditorStatus"] = "Processed";
        info["AccessibilityAuditorAltTextInstructions"] = instructions.AltTexts.Count.ToString();
        info["AccessibilityAuditorTableSummaryInstructions"] = instructions.TableSummaries.Count.ToString();
        info["AccessibilityAuditorRemediationMode"] = remediationMode.ToString();

        stamper.MoreInfo = info;
    }


    private static string GetString(JsonElement element, string propertyName)
    {
        if (element.TryGetProperty(propertyName, out var value))
        {
            if (value.ValueKind == JsonValueKind.String)
                return value.GetString() ?? "";

            return value.ToString();
        }

        return "";
    }


    private static int? GetNullableInt(JsonElement element, string propertyName)
    {
        if (element.TryGetProperty(propertyName, out var value) &&
            value.ValueKind == JsonValueKind.Number &&
            value.TryGetInt32(out var number))
        {
            return number;
        }

        return null;
    }

    private static double? GetNullableDouble(JsonElement element, string propertyName)
    {
        if (element.TryGetProperty(propertyName, out var value) &&
            value.ValueKind == JsonValueKind.Number &&
            value.TryGetDouble(out var number))
        {
            return number;
        }

        return null;
    }

    private static bool? GetNullableBool(JsonElement element, string propertyName)
    {
        if (element.TryGetProperty(propertyName, out var value))
        {
            if (value.ValueKind == JsonValueKind.True)
                return true;

            if (value.ValueKind == JsonValueKind.False)
                return false;
        }

        return null;
    }

    private static PdfRemediationMode DetermineRemediationMode(PdfReader reader)
    {
        var catalog = reader.Catalog;
        var structTreeRoot = catalog.GetAsDict(PdfName.STRUCTTREEROOT);
        var markInfo = catalog.GetAsDict(PdfName.MARKINFO);
        var parentTree = structTreeRoot?.Get(PdfName.PARENTTREE);
        var marked = markInfo?.GetAsBoolean(PdfName.MARKED)?.BooleanValue ?? false;

        if (structTreeRoot is not null && markInfo is not null && marked && parentTree is not null)
            return PdfRemediationMode.TaggedPdf;

        if (structTreeRoot is null && parentTree is null)
            return PdfRemediationMode.UntaggedPdf;

        return PdfRemediationMode.Unknown;
    }

    private static void AddModeMessages(
        UploadJobResult job,
        PdfRemediationMode mode)
    {
        if (mode == PdfRemediationMode.TaggedPdf)
        {
            job.Messages.Add("Tagged PDF detected. The PDF has StructTreeRoot, MarkInfo/Marked, and ParentTree.");
            job.Messages.Add("Current edit mode: tagged-PDF path. Alt-text and table-summary updates will be attempted against matching /Figure and /Table elements.");
            return;
        }

        if (mode == PdfRemediationMode.UntaggedPdf)
        {
            job.Messages.Add("Untagged PDF detected. The PDF does not expose reliable /Figure or /Table structure elements for direct injection. Generated captions and summaries remain in the separate summary file.");
            return;
        }

        job.Messages.Add("PDF tagging status is incomplete or uncertain.");
        job.Messages.Add("Current edit mode: conservative fallback path. Generated captions and summaries remain in the separate summary file when direct element updates are not safe.");
    }


    private static string GetObjectKey(PdfObject item)
    {
        if (item is PRIndirectReference prRef)
            return $"{prRef.Number}:{prRef.Generation}";

        if (item is PdfIndirectReference indirectRef)
            return indirectRef.ToString();

        return "";
    }


    private static Dictionary<string, int> BuildPageReferenceMap(PdfReader reader)
    {
        var map = new Dictionary<string, int>();

        for (var pageNumber = 1; pageNumber <= reader.NumberOfPages; pageNumber++)
        {
            var pageReference = reader.GetPageOrigRef(pageNumber);
            var key = GetObjectKey(pageReference);

            if (!string.IsNullOrWhiteSpace(key))
                map[key] = pageNumber;
        }

        return map;
    }


    private static List<int> ExtractMarkedContentIds(PdfObject? item)
    {
        var ids = new List<int>();
        var visitedObjects = new HashSet<string>();

        ExtractMarkedContentIdsRecursive(
            item,
            ids,
            visitedObjects
        );

        return ids
            .Distinct()
            .ToList();
    }

    private static void ExtractMarkedContentIdsRecursive(
        PdfObject? item,
        List<int> ids,
        HashSet<string> visitedObjects)
    {
        if (item is null)
            return;

        var objectKey = GetObjectKey(item);

        if (!string.IsNullOrWhiteSpace(objectKey) && !visitedObjects.Add(objectKey))
            return;

        var resolved = PdfReader.GetPdfObject(item);

        if (resolved is PdfNumber number)
        {
            ids.Add(number.IntValue);
            return;
        }

        if (resolved is PdfArray array)
        {
            for (var i = 0; i < array.Size; i++)
            {
                ExtractMarkedContentIdsRecursive(
                    array.GetPdfObject(i),
                    ids,
                    visitedObjects
                );
            }

            return;
        }

        if (resolved is PdfDictionary dict)
        {
            var mcid = dict.GetAsNumber(PdfName.MCID);

            if (mcid is not null)
                ids.Add(mcid.IntValue);

            var nestedKids = dict.Get(PdfName.K);

            if (nestedKids is not null)
            {
                ExtractMarkedContentIdsRecursive(
                    nestedKids,
                    ids,
                    visitedObjects
                );
            }
        }
    }


    private static string NormalizeSpacing(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return "";

        return string.Join(
            " ",
            value.Split(
                ' ',
                StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries
            )
        );
    }

    private static string TrimMessageText(string value)
    {
        value = NormalizeSpacing(value);

        if (value.Length <= 80)
            return value;

        return value[..80] + "...";
    }


}