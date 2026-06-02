@echo off
cd /d D:\Projects\Novel_Creater
if not exist tmp\realistic-flow-qa mkdir tmp\realistic-flow-qa
set REALISTIC_QA_INITIAL_TO_CHAPTER=5
set REALISTIC_QA_PROJECT_PREFIX=WritingProfileQA200w
set REALISTIC_QA_PRIMARY_STANDARD=rational-fantasy
set REALISTIC_QA_SECONDARY_FLAVOR=suspense-hook
D:\Software\nodejs\node.exe tmp\run_realistic_longform_flow.mjs > tmp\realistic-flow-qa\standards-run.out.log 2> tmp\realistic-flow-qa\standards-run.err.log
