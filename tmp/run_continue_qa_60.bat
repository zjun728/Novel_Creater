@echo off
cd /d D:\Projects\Novel_Creater
set RESUME_REALISTIC_QA_PROJECT_ID=01abd042-0f56-4741-a4f4-be8fde0a7958
set CONTINUE_REALISTIC_QA_TO_CHAPTER=60
D:\Software\nodejs\node.exe tmp\run_realistic_longform_flow.mjs > tmp\realistic-flow-qa\continue-60-bg-stdout.log 2> tmp\realistic-flow-qa\continue-60-bg-stderr.log
