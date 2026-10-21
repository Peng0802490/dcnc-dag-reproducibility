param(
    [string]$DeliveryName = "new_7_2_simulation_deliverables_20260723"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$stage = Join-Path $root $DeliveryName
$zipPath = "$stage.zip"

if (Test-Path -LiteralPath $stage) {
    throw "Staging directory already exists: $stage"
}
if (Test-Path -LiteralPath $zipPath) {
    throw "ZIP already exists: $zipPath"
}

$directories = @(
    "docs",
    "scripts",
    "results/canonical",
    "results/capacity",
    "results/instance_contract",
    "results/observer_validation",
    "results/second_pass",
    "results/wireless"
)
New-Item -ItemType Directory -Path $stage | Out-Null
foreach ($directory in $directories) {
    New-Item -ItemType Directory -Path (Join-Path $stage $directory) | Out-Null
}

$copies = @(
    @{ Source = "new_7.2_instance_simulation_delivery_readme.md"; Destination = "README.md" },
    @{ Source = "new_7.2_instance_simulation_spec.md"; Destination = "docs/new_7.2_instance_simulation_spec.md" },
    @{ Source = "new_7.2_instance_simulation_report.md"; Destination = "docs/new_7.2_instance_simulation_report.md" },
    @{ Source = "new_7.2_instance_simulation_correction_log.md"; Destination = "docs/new_7.2_instance_simulation_correction_log.md" },
    @{ Source = "new_7.2_instance_simulation_reproduction.md"; Destination = "docs/new_7.2_instance_simulation_reproduction.md" },
    @{ Source = "scripts/run_new_7_2_wireless_mixed_mapping.py"; Destination = "scripts/run_new_7_2_wireless_mixed_mapping.py" },
    @{ Source = "scripts/validate_new_7_2_capacity_lp.py"; Destination = "scripts/validate_new_7_2_capacity_lp.py" },
    @{ Source = "scripts/audit_new_7_2_results.py"; Destination = "scripts/audit_new_7_2_results.py" },
    @{ Source = "scripts/second_pass_new_7_2_audit.py"; Destination = "scripts/second_pass_new_7_2_audit.py" },
    @{ Source = "scripts/verify_new_7_2_instance_contract.py"; Destination = "scripts/verify_new_7_2_instance_contract.py" },
    @{ Source = "scripts/audit_new_7_2_wireless_paths.py"; Destination = "scripts/audit_new_7_2_wireless_paths.py" },
    @{ Source = "scripts/validate_new_7_2_metric_observer.py"; Destination = "scripts/validate_new_7_2_metric_observer.py" },
    @{ Source = "scripts/package_new_7_2_deliverables.ps1"; Destination = "scripts/package_new_7_2_deliverables.ps1" },
    @{ Source = "results_new_7_2_validation_20260723/canonical/lp_decomposition.csv"; Destination = "results/canonical/lp_decomposition.csv" },
    @{ Source = "results_new_7_2_validation_20260723/canonical/metadata.json"; Destination = "results/canonical/metadata.json" },
    @{ Source = "results_new_7_2_validation_20260723/canonical/runs.csv"; Destination = "results/canonical/runs.csv" },
    @{ Source = "results_new_7_2_validation_20260723/canonical/summary.csv"; Destination = "results/canonical/summary.csv" },
    @{ Source = "results_new_7_2_validation_20260723/canonical/paper_table_main.csv"; Destination = "results/canonical/paper_table_main.csv" },
    @{ Source = "results_new_7_2_validation_20260723/canonical/paper_table_ablation.csv"; Destination = "results/canonical/paper_table_ablation.csv" },
    @{ Source = "results_new_7_2_validation_20260723/canonical/audit_report.json"; Destination = "results/canonical/audit_report.json" },
    @{ Source = "results_new_7_2_validation_20260723/capacity_lp_audit.json"; Destination = "results/capacity/capacity_lp_audit.json" },
    @{ Source = "results_new_7_2_validation_20260723/capacity_lp_link_audit.csv"; Destination = "results/capacity/capacity_lp_link_audit.csv" },
    @{ Source = "results_new_7_2_validation_20260723/instance_contract/instance_contract_audit.json"; Destination = "results/instance_contract/instance_contract_audit.json" },
    @{ Source = "results_new_7_2_validation_20260723/observer_validation/scan_reference_runs_64.csv"; Destination = "results/observer_validation/scan_reference_runs_64.csv" },
    @{ Source = "results_new_7_2_validation_20260723/observer_validation/metric_observer_validation.json"; Destination = "results/observer_validation/metric_observer_validation.json" },
    @{ Source = "results_new_7_2_validation_20260723/second_pass_canonical/second_pass_runs.csv"; Destination = "results/second_pass/second_pass_runs.csv" },
    @{ Source = "results_new_7_2_validation_20260723/second_pass_canonical/physical_metric_summary.csv"; Destination = "results/second_pass/physical_metric_summary.csv" },
    @{ Source = "results_new_7_2_validation_20260723/second_pass_canonical/second_pass_report.json"; Destination = "results/second_pass/second_pass_report.json" },
    @{ Source = "results_new_7_2_validation_20260723/wireless_path_audit/wireless_seed_paths.csv"; Destination = "results/wireless/wireless_seed_paths.csv" },
    @{ Source = "results_new_7_2_validation_20260723/wireless_path_audit/wireless_joint_state_counts.csv"; Destination = "results/wireless/wireless_joint_state_counts.csv" },
    @{ Source = "results_new_7_2_validation_20260723/wireless_path_audit/wireless_path_audit.json"; Destination = "results/wireless/wireless_path_audit.json" }
)

foreach ($copy in $copies) {
    $source = Join-Path $root $copy.Source
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Required delivery file is missing: $source"
    }
    Copy-Item -LiteralPath $source -Destination (Join-Path $stage $copy.Destination)
}

$checksumLines = Get-ChildItem -LiteralPath $stage -Recurse -File |
    Sort-Object FullName |
    ForEach-Object {
        $relative = $_.FullName.Substring($stage.Length).TrimStart([char[]]"\/").Replace("\", "/")
        $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  $relative"
    }
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllLines(
    (Join-Path $stage "SHA256SUMS.txt"),
    [string[]]$checksumLines,
    $utf8NoBom
)

Compress-Archive -LiteralPath $stage -DestinationPath $zipPath -CompressionLevel Optimal

Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::OpenRead($zipPath)
try {
    $fileEntries = @(
        $archive.Entries |
            Where-Object {
                -not ($_.FullName.EndsWith("/") -or $_.FullName.EndsWith("\"))
            }
    )
    $expectedFiles = @(Get-ChildItem -LiteralPath $stage -Recurse -File)
    if ($fileEntries.Count -ne $expectedFiles.Count) {
        throw "ZIP entry count $($fileEntries.Count) differs from staged file count $($expectedFiles.Count)"
    }
    foreach ($entry in $fileEntries) {
        $normalizedName = $entry.FullName.Replace("\", "/")
        if ($normalizedName -match '(^|/)(\.git|\.ssh)(/|$)|token|credential') {
            throw "Forbidden or sensitive-looking ZIP entry: $($entry.FullName)"
        }
        $stream = $entry.Open()
        try {
            $buffer = New-Object byte[] 81920
            while ($stream.Read($buffer, 0, $buffer.Length) -gt 0) { }
        }
        finally {
            $stream.Dispose()
        }
    }
}
finally {
    $archive.Dispose()
}

$zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
[pscustomobject]@{
    StagingDirectory = $stage
    ZipPath = $zipPath
    FileCount = (Get-ChildItem -LiteralPath $stage -Recurse -File).Count
    ZipBytes = (Get-Item -LiteralPath $zipPath).Length
    ZipSHA256 = $zipHash
}
