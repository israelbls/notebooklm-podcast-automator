"""API routes for NotebookLM Automator."""

import os
import subprocess

from fastapi import APIRouter, Depends, HTTPException, Response

from notebooklm_automator.api.models import (
    AudioStatusResponse,
    ClearSourcesResponse,
    ClearStudioResponse,
    GenerateAudioRequest,
    GenerateAudioResponse,
    SourceResult,
    UploadResponse,
    UploadSourcesRequest,
)
from notebooklm_automator.core.automator import NotebookLMAutomator


router = APIRouter()

_automator_instance: NotebookLMAutomator = None


def get_automator() -> NotebookLMAutomator:
    """Get or create the automator instance."""
    global _automator_instance
    if not _automator_instance:
        url = os.getenv("NOTEBOOKLM_URL")
        if not url:
            raise HTTPException(
                status_code=500,
                detail="NOTEBOOKLM_URL environment variable not set",
            )
        port = int(os.getenv("NOTEBOOKLM_CHROME_PORT", "9222"))
        _automator_instance = NotebookLMAutomator(notebook_url=url, port=port)
        try:
            _automator_instance.connect()
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to connect to NotebookLM: {str(e)}",
            )
    return _automator_instance


@router.post("/sources/upload", response_model=UploadResponse)
def upload_sources(
    request: UploadSourcesRequest,
    automator: NotebookLMAutomator = Depends(get_automator),
):
    """Upload one or more sources to the notebook."""
    sources_data = [s.model_dump() for s in request.sources]
    results_data = automator.add_sources(sources_data)

    results = [SourceResult(**r) for r in results_data]
    overall_success = all(r.success for r in results)
    automator.page.close()
    return UploadResponse(overall_success=overall_success, results=results)


@router.post("/sources/clear", response_model=ClearSourcesResponse)
def clear_sources(automator: NotebookLMAutomator = Depends(get_automator)):
    """Clear all sources from the notebook."""
    result = automator.clear_sources()
    automator.page.close()
    return ClearSourcesResponse(
        success=result.get("success", False),
        count=result.get("count", 0),
        message=result.get("message"),
    )


@router.post("/audio/generate", response_model=GenerateAudioResponse)
def generate_audio(
    request: GenerateAudioRequest,
    automator: NotebookLMAutomator = Depends(get_automator),
):
    """Trigger audio generation."""
    try:
        job_id = automator.generate_audio(
            style=request.style.value if request.style else None,
            language=request.language,
            prompt=request.prompt,
        )
        automator.page.close()
        return GenerateAudioResponse(job_id=job_id, status="started")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/audio/status/{job_id}", response_model=AudioStatusResponse)
def check_audio_status(
    job_id: str,
    automator: NotebookLMAutomator = Depends(get_automator),
):
    """Check the status of audio generation."""
    status_data = automator.get_audio_status(job_id)

    download_url = None
    if status_data["status"] == "completed":
        download_url = automator.get_download_url(job_id)
    else:
        automator.page.close()

    return AudioStatusResponse(
        job_id=job_id,
        status=status_data["status"],
        download_url=download_url,
    )


@router.get("/audio/file/{job_id}")
def get_audio_download_url(
    job_id: str,
    automator: NotebookLMAutomator = Depends(get_automator),
):
    """Return the direct download URL for generated audio."""
    status_data = automator.get_audio_status(job_id)
    if status_data["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail="Audio generation not completed or failed",
        )

    url = automator.get_download_url(job_id)
    automator.page.close()
    if not url:
        raise HTTPException(
            status_code=500,
            detail="Could not retrieve download URL",
        )

    return {"url": url}


@router.get("/audio/download/{job_id}")
def download_audio_file(
    job_id: str,
    automator: NotebookLMAutomator = Depends(get_automator),
):
    """Download audio file as binary data.

    Returns the actual audio file content as binary data.
    """
    status_data = automator.get_audio_status(job_id)

    if status_data["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail="Audio generation not completed or failed",
        )

    # Download by clicking Download button in UI (uses browser's fast QUIC/HTTP3)
    result = automator.download_audio_file(job_id)
    automator.page.close()

    if not result:
        raise HTTPException(
            status_code=500,
            detail="Failed to download audio file",
        )

    content, file_name, file_size = result

    import re
    safe_file_name = re.sub(r"[^A-Za-z0-9._-]+", "_", file_name)

    return Response(
        content=content,
        media_type="audio/mp4",
        headers={
            "Content-Disposition": f"attachment; filename={safe_file_name}",
            "Content-Length": str(file_size),
        },
    )


@router.post("/studio/clear", response_model=ClearStudioResponse)
def clear_studio(automator: NotebookLMAutomator = Depends(get_automator)):
    """Delete all generated audio items."""
    result = automator.clear_studio()
    automator.page.close()
    return ClearStudioResponse(
        success=result.get("success", False),
        count=result.get("count", 0),
        message=result.get("message"),
    )


# Test type to directory mapping
TEST_PATHS = {
    "unit": "tests/unit/",
    "api": "tests/api/",
    "ui": "tests/ui/",
    "e2e": "tests/e2e/",
    "all": "tests/",
}


@router.post("/run-tests")
def run_tests(test_type: str = "all", verbose: bool = False):
    """Trigger the test suite.

    Args:
        test_type: Type of tests to run (unit, api, ui, e2e, all). Default: all
        verbose: Enable verbose output. Default: False

    Returns:
        JSON with success status, output, errors, and test summary.
    """
    if test_type not in TEST_PATHS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid test_type. Must be one of: {', '.join(TEST_PATHS.keys())}",
        )

    test_path = TEST_PATHS[test_type]

    # Build pytest command
    cmd = ["python", "-m", "pytest", test_path]
    if verbose:
        cmd.append("-v")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        # Parse test summary from output
        summary = _parse_test_summary(result.stdout)

        return {
            "success": result.returncode == 0,
            "test_type": test_type,
            "exit_code": result.returncode,
            "summary": summary,
            "output": result.stdout,
            "error": result.stderr if result.stderr else None,
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail="Test execution timed out after 5 minutes",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to run tests: {str(e)}",
        )


def _parse_test_summary(output: str) -> dict:
    """Parse pytest output to extract test summary.

    Args:
        output: Raw pytest stdout

    Returns:
        Dictionary with passed, failed, skipped counts
    """
    summary = {
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "errors": 0,
        "total": 0,
    }

    # Look for summary line like "5 passed, 2 failed, 1 skipped"
    lines = output.split("\n")
    for line in reversed(lines):
        line_lower = line.lower()
        if "passed" in line_lower or "failed" in line_lower:
            import re

            # Extract numbers
            passed = re.search(r"(\d+)\s*passed", line_lower)
            failed = re.search(r"(\d+)\s*failed", line_lower)
            skipped = re.search(r"(\d+)\s*skipped", line_lower)
            errors = re.search(r"(\d+)\s*error", line_lower)

            if passed:
                summary["passed"] = int(passed.group(1))
            if failed:
                summary["failed"] = int(failed.group(1))
            if skipped:
                summary["skipped"] = int(skipped.group(1))
            if errors:
                summary["errors"] = int(errors.group(1))

            summary["total"] = (
                summary["passed"]
                + summary["failed"]
                + summary["skipped"]
                + summary["errors"]
            )
            break

    return summary
