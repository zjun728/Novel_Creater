# Real Corpus Prompt Hookup Phase 3.2 Report

Status: deterministic no-live prompt assembly gate. This report does not claim live generation, real DB migration, real project regression, model validation, or production prompt default rollout.

## Scope Guard
- Did not start backend/frontend dev server, runner, or page.goto.
- Did not run formal chapter generation/finalization chain.
- Did not connect to or write a real DB.
- Did not touch real project data, restore LongformBrowser, or run #98/#99/#50.
- Did not run a model or enter provider/model adapter code.
- Did not save model output as project body, outline, beat plan, or DB state.
- Did not push or create PR.

## Branch
branch.current=codex/novel-creater-sample-library-v3-prompt-hookup
branch.baseCommit=a326c7d
branch.headCommit=a326c7d

## Hookup Design Audit
promptEntryPoint=frontend/src/prompts/chapterDraftPrompt.js buildDraftPrompt -> frontend/src/prompts/chapter.js buildChapterPrompt
insertionPoint=after Scene Execution Card and Narrative Voice Contract, before state/fact-heavy prompt sections
formatter=frontend/src/data/realCorpusExperienceCardsV3.js formatRealCorpusExperienceForPrompt
optInFlag=enableRealCorpusExperienceCards
cardInput=context.realCorpusExperienceCards
expressionOnly=true
doesNotEnterStateAuthority=true
defaultProductionEnabled=false

## Formatter Budget
budget.maxSections=1
budget.maxCardsWithoutFormalStandard=2
budget.maxCardsWithFormalStandard=1
budget.defaultMaxSectionChars=1000
budget.formalStandardMaxSectionChars=760

## Six-Scene Prompt Evidence
| scene | selected_cards | expected_tag_hit | helper_chars | signal_lift | source_leak | future_leak | budget_violation |
| --- | ---: | --- | ---: | ---: | --- | --- | --- |
| interrogation_negotiation | 2 | true | 659 | 34 | false | false | false |
| conflict_dialogue | 2 | true | 659 | 34 | false | false | false |
| chase_action_burst | 2 | true | 659 | 34 | false | false | false |
| intimate_fracture | 2 | true | 679 | 34 | false | false | false |
| before_reveal | 2 | true | 687 | 35 | false | false | false |
| failure_aftermath | 2 | true | 673 | 29 | false | false | false |

## Summary
summary.sceneCount=6
summary.helperScenes=6
summary.futureLeaks=0
summary.sourceLeaks=0
summary.lowSignalSelectedCards=0
summary.promptBudgetViolations=0
summary.sampleV3PromptRegressions=0
summary.averageNoSampleScore=120.5
summary.averageSampleScore=153.83
summary.averageSignalLift=33.33

## Model Assisted Validation
model.used=false
model.reason=Phase 3.2 request forbids model runs; deterministic no-model prompt assembly evidence is the hard gate.

## Remaining Risks
- V3 helper is opt-in and no-live only in this phase; production rollout still needs a later gate.
- No model prose sample was generated; this phase proves prompt assembly boundaries and prompt-level signals only.
- Human editorial review remains recommended before default enablement.
