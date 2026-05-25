$ErrorActionPreference = "Stop"
$base = if ($env:NOVEL_SMOKE_BASE) { $env:NOVEL_SMOKE_BASE } else { "http://127.0.0.1:8000/api" }

function To-JsonBody($value) {
  return ($value | ConvertTo-Json -Depth 20 -Compress)
}

function Api($method, $path, $body = $null, [switch]$AllowError) {
  Write-Host "CALL $method $path"
  $params = @{
    Method = $method
    Uri = "$base$path"
    TimeoutSec = 20
  }
  if ($null -ne $body) {
    $params.ContentType = "application/json; charset=utf-8"
    $params.Body = To-JsonBody $body
  }
  try {
    return Invoke-RestMethod @params
  } catch {
    if ($AllowError) {
      return $_.Exception.Response
    }
    throw
  }
}

function Assert($condition, $message) {
  if (-not $condition) {
    throw "ASSERT_FAILED: $message"
  }
}

$project = $null

try {
  $health = Api GET "/health"
  Assert $health.ok "backend health should be ok"

  $project = Api POST "/projects" @{
    title = "Codex v1 smoke"
    genre = "urban fantasy"
    description = "v1 end-to-end smoke project"
    targetWords = 100000
    targetChapters = 100
  }
  Assert $project.id "project should be created"
  $projectId = $project.id

  $state0 = Api GET "/projects/$projectId/content-state"
  Assert (-not $state0.hasChapterContent) "empty project should not have chapter content"

  $seed = Api POST "/projects/$projectId/seeds" @{
    title = "Three Realms Chat"
    genre = "urban fantasy"
    logline = "An atheist student enters an immortal work group chat."
    protagonist = "Shen Ye, college student."
    desire = "Find out whether the group chat is a prank."
    coreConflict = "Both maintaining and breaking the seal have a cost."
    worldPressure = "The late-spiritual era is running out of resources."
    openingHook = "A Three Realms colleague group pops up on his phone."
    emotionalPromise = "Comedy opening, bittersweet ending."
    differentiation = "The group chat is the epic foundation."
    styleTarget = "Fast webnovel pace with restrained mystery."
    riskNotes = "Avoid filler chat logs."
    endingAnchor = "The protagonist lights the way and enters chaos."
    source = "smoke"
  }
  Assert ($seed.endingAnchor -like "*chaos*") "seed endingAnchor should be saved"

  $bible = Api PUT "/projects/$projectId/bible" @{
    premise = "An atheist student enters an immortal work group chat."
    targetReader = "Readers who like urban fantasy, group chat comedy, and mystery reversals."
    styleBible = "Every chat message should carry comedy, foreshadowing, or worldbuilding."
    themeBible = "People choose different answers in front of the same impossible dilemma."
    worldRules = "The late-spiritual era is irreversible, and the seal dilemma hangs overhead."
    confirmedSettings = @("Fengyuan bloodline")
    forbiddenDirections = @("Do not write the group chat as a pure cheat tool")
  }
  Assert ($bible.targetReader -like "*urban fantasy*") "bible targetReader should be saved"

  $change = Api POST "/projects/$projectId/settings/change-events" @{
    entityType = "character"
    entityName = "Shen Ye"
    changeType = "new_entity"
    fieldPath = "summary"
    newValue = @{
      summary = "Main character and descendant of Fengyuan."
      category = "protagonist"
      importance = 10
      profile = @{ age = "20"; identity = "college student" }
      tags = @("protagonist", "seal")
    }
    evidence = "[init] from bible"
    confidence = 0.9
    status = "pending_review"
  }
  $accepted = Api POST "/projects/$projectId/settings/change-events/$($change.id)/accept"
  Assert $accepted.ok "setting change should be accepted"
  $entities = Api GET "/projects/$projectId/settings/entities"
  Assert (@($entities | Where-Object { $_.name -eq "Shen Ye" }).Count -ge 1) "setting entity should be created"

  $volume = Api POST "/projects/$projectId/volumes" @{
    volumeNum = 1
    title = "Entry and Awakening"
    startChapter = 1
    endChapter = 10
    targetWords = 30000
    coreGoal = "Confirm the group chat is not a prank"
    mainConflict = "Scientific explanation versus abnormal evidence"
    keyCharacters = @("Shen Ye")
    summary = "The first volume establishes the world."
    status = "planned"
  }
  Assert $volume.id "volume should be created"

  $chapter = Api POST "/projects/$projectId/chapters" @{ chapterNum = 1; title = "Chapter 1 Entry" }
  Assert $chapter.id "chapter should be created"

  $beat = Api PUT "/projects/$projectId/chapter-beat-plan/1" @{ content = "1. Parcel station entry.`n2. Group chat comedy.`n3. Shen Ye finds the anomaly." }
  Assert ($beat.content -like "*Parcel*") "beat plan should be saved"

  $version = Api POST "/projects/$projectId/chapters/$($chapter.id)/versions" @{
    title = "Candidate text"
    content = "Shen Ye crouched outside the parcel station with instant noodles when the Three Realms work group lit up on his phone."
    versionType = "ai_candidate"
    promptBrief = "smoke"
  }
  Assert $version.id "chapter version should be created"

  $finalChapter = Api PUT "/projects/$projectId/chapters/$($chapter.id)" @{
    finalVersionId = $version.id
    status = "final"
    summary = "Shen Ye enters the Three Realms group."
    wordCount = 21
  }
  Assert ($finalChapter.finalVersionId -eq $version.id) "chapter should be finalized"

  $state1 = Api GET "/projects/$projectId/content-state"
  Assert $state1.hasChapterContent "finalized chapter should count as content"

  $blocked = Api PUT "/projects/$projectId" @{ targetWords = 120000 } -AllowError
  Assert ($blocked.StatusCode.value__ -eq 400) "targetWords update should be blocked after content"

  $audit = Api POST "/projects/$projectId/global-audits" @{
    reportType = "global"
    title = "Smoke audit"
    report = @{
      criticalIssues = @(@{
        type = "continuity"
        description = "The Fengyuan title should be consistent."
        impact = "May hurt continuity."
        suggestion = "Use one spelling."
        severity = "major"
        chapterRefs = @(1)
        relatedItems = @("Shen Ye")
      })
      nextActions = @("Confirm title spelling")
    }
  }
  Assert $audit.id "global audit should be saved"

  $task = Api POST "/projects/$projectId/correction-tasks" @{
    sourceType = "global_audit"
    sourceId = $audit.id
    targetModule = "canon"
    title = "Unify Fengyuan title"
    description = "The title should be consistent."
    severity = "major"
    issueType = "continuity"
    chapterRefs = @(1)
    relatedItems = @("Shen Ye")
    suggestedAction = "Use one spelling"
    status = "pending"
    metadata = @{ smoke = $true }
  }
  $ignored = Api PUT "/projects/$projectId/correction-tasks/$($task.id)" @{ status = "ignored" }
  Assert ($ignored.status -eq "ignored") "correction task ignored status should persist"

  $ignoredList = Api GET "/projects/$projectId/correction-tasks?status=ignored"
  Assert (@($ignoredList | Where-Object { $_.id -eq $task.id }).Count -eq 1) "ignored task should be queryable"

  "SMOKE_OK project=$projectId"
} finally {
  if ($null -ne $project -and $project.id) {
    try {
      Api DELETE "/projects/$($project.id)" | Out-Null
      "CLEANUP_OK project=$($project.id)"
    } catch {
      "CLEANUP_FAILED project=$($project.id) error=$($_.Exception.Message)"
    }
  }
}
