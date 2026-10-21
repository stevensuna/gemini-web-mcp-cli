# Code Execution (Python Sandbox)

## Status: NOT CAPTURED -- Manual RPC capture required

## Overview

Gemini can execute Python code in a sandboxed environment. This is used for
calculations, data analysis, generating charts, and running code snippets.

## What We Know

- Code execution is available through the Gemini web UI
- Python code runs in a sandboxed environment
- Can produce text output, charts, and files
- gemini-webapi does NOT implement this
- The model may auto-execute code as part of its response

## Capture Plan

1. Open Chrome DevTools > Network tab
2. Filter to Fetch/XHR
3. Trigger code execution in Gemini:
   a. Ask Gemini to run a Python calculation
   b. Ask Gemini to create a chart/plot
   c. Ask Gemini to analyze data
4. Watch for:
   - Is code execution part of the standard StreamGenerate response?
   - Or is there a separate RPC for code execution?
   - How are execution results (stdout, files, plots) returned?
5. Export HAR file to `captures/har/code-execution.har`
6. Extract cURL commands to `captures/curl/code-execution.sh`

## Questions to Answer During Capture

- Is code execution triggered through regular chat or a separate mechanism?
- How is code output returned (inline text, file URLs, embedded images)?
- Can the user explicitly request code execution, or does the model decide?
- What are the sandbox limitations (libraries, execution time, file access)?
- Are generated files (charts, CSVs) downloadable? What are the URLs?
- Is there a way to specify the execution environment or install packages?
