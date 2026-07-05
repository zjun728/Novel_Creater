# Offline Narrative Quality Regression Phase 2.1 Report

Status: offline regression completed with synthetic fixtures; no live chapter chain or DB writes.

## Scope Guard
- Did not start backend/frontend dev server, runner, or page.goto.
- Did not run formal chapter generation/finalization chain.
- Did not write real DB data or execute migrations/cleanup.
- Did not restore LongformBrowser or run #98/#99/#50.
- Did not save model output as project正文、小纲、beat plan, or DB state.
- Did not enter Phase 3 provider adapter work.

## Provider
preferredModelRequested=联通云-DeepSeek-V4-Flash
providerName=DeepSeek fallback
providerModel=deepseek-v4-pro
mode=offline-model
reasonForFallback=当前线程未暴露可用的联通云未脱敏 baseURL/apiKey；使用环境中可见的 DeepSeek fallback key 做离线 QA。

## Summary
fixtureCount=6
averageOldScore=93
averageNewScore=100
oldPromptPasses=4
newPromptPasses=6
oldPromptFutureLeaks=0
newPromptFutureLeaks=0
newPromptRegressions=0
newPromptOverallNonRegression=true
futureLeakDefinition=exactFutureSecretLeak_or_futureLeakRiskTerms

## Fixture Coverage
| id | category | trusted facts | conflict | emotional turn | stop point | guard-only secret |
| --- | --- | --- | --- | --- | --- | --- |
| interrogation-negotiation | interrogation_negotiation | true | 林遥 vs 周岑 | 林遥从压着怒意试探，转为意识到周岑是在保护另一个人。 | 周岑只说出账本在旧码头三号仓，不说出买家。 | true |
| conflict-dialogue | conflict_dialogue | true | 许砚 vs 夏弦 | 许砚从公开指控，转为意识到夏弦删页是在替队伍挡一次清洗。 | 夏弦承认删页，但不说盟约原件已经外流。 | true |
| chase-action-burst | chase_action_burst | true | 白澈 vs 黑衣追逐者 | 白澈从把对方当敌人，转为发现对方故意把他引离爆炸路线。 | 白澈夺回腕包，但不能知道追逐者真实身份。 | true |
| intimate-relationship-crack | intimate_relationship裂隙 | true | 陆知白 vs 闻笙 | 陆知白从质问她变心，转为意识到她在准备独自承担风险。 | 闻笙承认要离开一段时间，但不说调令已经签好。 | true |
| pre-reveal-night | pre_reveal_night | true | 沈微 vs 档案管理员 | 沈微从以为管理员失职，转为意识到管理员在替她拖延开盒时间。 | 管理员承认有人调换编号，但不说档案盒真实身份。 | true |
| post-battle-failure-aftermath | post_battle_failure_aftermath | true | 姜朔 vs 剩余队员秦澜 | 姜朔从用命令压住愧疚，转为承认自己错判害队伍失去副队长。 | 姜朔决定回收遗留装备，但不能发现撤退密码。 | true |

## A/B Results
| fixture | old score/pass/issues/leak | new score/pass/issues/leak | delta | regressed |
| --- | --- | --- | --- | --- |
| interrogation_negotiation | oldPrompt.qualityScore=100; oldPrompt.passedEvaluator=true; oldPrompt.blockingIssueCodes=none; oldPrompt.warningIssueCodes=missing_short_interiority; oldPrompt.exactFutureSecretLeak=false; oldPrompt.futureLeakRisk=false; oldPrompt.futureLeakRiskTerms=none; oldPrompt.leakedFutureSecret=false | newPrompt.qualityScore=100; newPrompt.passedEvaluator=true; newPrompt.blockingIssueCodes=none; newPrompt.warningIssueCodes=missing_short_interiority; newPrompt.exactFutureSecretLeak=false; newPrompt.futureLeakRisk=false; newPrompt.futureLeakRiskTerms=none; newPrompt.leakedFutureSecret=false | scoreDelta=0 | newPromptRegressed=false |
| conflict_dialogue | oldPrompt.qualityScore=79; oldPrompt.passedEvaluator=false; oldPrompt.blockingIssueCodes=low_dialogue_conflict; oldPrompt.warningIssueCodes=missing_short_interiority; oldPrompt.exactFutureSecretLeak=false; oldPrompt.futureLeakRisk=false; oldPrompt.futureLeakRiskTerms=none; oldPrompt.leakedFutureSecret=false | newPrompt.qualityScore=100; newPrompt.passedEvaluator=true; newPrompt.blockingIssueCodes=none; newPrompt.warningIssueCodes=none; newPrompt.exactFutureSecretLeak=false; newPrompt.futureLeakRisk=false; newPrompt.futureLeakRiskTerms=none; newPrompt.leakedFutureSecret=false | scoreDelta=21 | newPromptRegressed=false |
| chase_action_burst | oldPrompt.qualityScore=79; oldPrompt.passedEvaluator=false; oldPrompt.blockingIssueCodes=low_dialogue_conflict; oldPrompt.warningIssueCodes=missing_short_interiority; oldPrompt.exactFutureSecretLeak=false; oldPrompt.futureLeakRisk=false; oldPrompt.futureLeakRiskTerms=none; oldPrompt.leakedFutureSecret=false | newPrompt.qualityScore=100; newPrompt.passedEvaluator=true; newPrompt.blockingIssueCodes=none; newPrompt.warningIssueCodes=missing_short_interiority; newPrompt.exactFutureSecretLeak=false; newPrompt.futureLeakRisk=false; newPrompt.futureLeakRiskTerms=none; newPrompt.leakedFutureSecret=false | scoreDelta=21 | newPromptRegressed=false |
| intimate_relationship裂隙 | oldPrompt.qualityScore=100; oldPrompt.passedEvaluator=true; oldPrompt.blockingIssueCodes=none; oldPrompt.warningIssueCodes=missing_short_interiority; oldPrompt.exactFutureSecretLeak=false; oldPrompt.futureLeakRisk=false; oldPrompt.futureLeakRiskTerms=none; oldPrompt.leakedFutureSecret=false | newPrompt.qualityScore=100; newPrompt.passedEvaluator=true; newPrompt.blockingIssueCodes=none; newPrompt.warningIssueCodes=missing_short_interiority; newPrompt.exactFutureSecretLeak=false; newPrompt.futureLeakRisk=false; newPrompt.futureLeakRiskTerms=none; newPrompt.leakedFutureSecret=false | scoreDelta=0 | newPromptRegressed=false |
| pre_reveal_night | oldPrompt.qualityScore=100; oldPrompt.passedEvaluator=true; oldPrompt.blockingIssueCodes=none; oldPrompt.warningIssueCodes=missing_short_interiority; oldPrompt.exactFutureSecretLeak=false; oldPrompt.futureLeakRisk=false; oldPrompt.futureLeakRiskTerms=none; oldPrompt.leakedFutureSecret=false | newPrompt.qualityScore=100; newPrompt.passedEvaluator=true; newPrompt.blockingIssueCodes=none; newPrompt.warningIssueCodes=none; newPrompt.exactFutureSecretLeak=false; newPrompt.futureLeakRisk=false; newPrompt.futureLeakRiskTerms=none; newPrompt.leakedFutureSecret=false | scoreDelta=0 | newPromptRegressed=false |
| post_battle_failure_aftermath | oldPrompt.qualityScore=100; oldPrompt.passedEvaluator=true; oldPrompt.blockingIssueCodes=none; oldPrompt.warningIssueCodes=missing_short_interiority; oldPrompt.exactFutureSecretLeak=false; oldPrompt.futureLeakRisk=false; oldPrompt.futureLeakRiskTerms=none; oldPrompt.leakedFutureSecret=false | newPrompt.qualityScore=100; newPrompt.passedEvaluator=true; newPrompt.blockingIssueCodes=none; newPrompt.warningIssueCodes=missing_short_interiority; newPrompt.exactFutureSecretLeak=false; newPrompt.futureLeakRisk=false; newPrompt.futureLeakRiskTerms=none; newPrompt.leakedFutureSecret=false | scoreDelta=0 | newPromptRegressed=false |

## Interpretation
Current sample supports architecture usability: new Scene Card prompt did not regress overall, did not trigger exact/risk-term future leak checks, and stayed within current-stage boundaries.

## Evidence Contract
- `tmp/test_offline_narrative_quality_regression_phase2_1.mjs` checks fixture coverage, prompt boundary, payload validity, and label-qualified report/JSON alignment.
- Report conclusions are derived from JSON fields; stale summary mutations are expected to fail the evidence matcher.
- Future leak checks combine exact future-secret string matching with fixture-level risk-term matching; this is deterministic QA evidence, not a claim of full semantic leak detection.

## Review
Fresh review subthread: 019f2eaf-9375-7be1-b705-368878a573b4
Critical=None
Important=None
Conclusion=Previous review 019f2e9d-8f4d-7553-8489-69389a6e4c91 found a row-level stale-value matcher gap; it was fixed locally with exact coverage/result row parsing and duplicate key rejection. Fresh Phase 2.1.1 review found no Critical/Important, no JSON/report drift, excerpt-only QA persistence, safe future-leak wording, and no boundary overrun.

## Verification
- node tmp\test_context_pack_v2_phase1_contract.mjs: passed
- node tmp\test_state_provenance_phase1_2_contract.mjs: passed
- node tmp\test_narrative_voice_scene_contract_phase2.mjs: passed
- node tmp\test_narrative_voice_phase2_evidence_contract.mjs: passed
- node tmp\test_offline_narrative_quality_regression_phase2_1.mjs: passed
- node tmp\test_quality_chain_contract.mjs: passed
- node tmp\test_quality_first_generation_contract.mjs: passed
- node tmp\test_prompt_boundary_modules.mjs: passed
- node tmp\test_writer_store_prompt_boundaries.mjs: passed
- node tmp\test_writing_style_standards_contract.mjs: passed
- node tmp\test_ai_trace_review_prompt.mjs: passed
- node tmp\test_audit_ai_trace_contract.mjs: passed
- strict JSON/report alignment probe: passed
- npm --prefix frontend run build: passed; existing Vite INEFFECTIVE_DYNAMIC_IMPORT warning only
