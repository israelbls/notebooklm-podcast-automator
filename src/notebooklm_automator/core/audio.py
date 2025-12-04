"""Audio generation and retrieval operations for NotebookLM Automator."""

import logging
import time
from typing import Any, Callable, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page

logger = logging.getLogger(__name__)


class AudioManager:
    """Manages audio generation and retrieval for a NotebookLM page."""

    def __init__(self, page: "Page", get_text: Callable[[str], str]):
        self.page = page
        self._get_text = get_text

    def generate(
        self,
        style: Optional[str] = None,
        prompt: Optional[str] = None,
        language: Optional[str] = None,
    ) -> str:
        """Generate an audio overview and return a job ID."""
        edit_icon = self.page.locator(
            "mat-icon:has-text('edit'), mat-icon.edit-button-icon"
        ).first
        if not edit_icon.is_visible():
            edit_btn = self.page.locator(
                "button:has(mat-icon:has-text('edit'))"
            ).first
            if edit_btn.is_visible():
                edit_btn.click()
            else:
                raise RuntimeError(
                    "Could not find Edit/Pencil icon for Audio Overview"
                )
        else:
            edit_icon.click(force=True)

        self.page.wait_for_selector("mat-dialog-container", state="visible")

        if style:
            style_text = self._get_text(f"{style}_radio_button")
            style_button = self.page.locator(
                f"mat-radio-button:has-text('{style_text}')"
            )
            if style_button.count() > 0 and style_button.is_visible():
                style_button.click()
            else:
                raise RuntimeError(
                    f"Could not find {style} radio button for Audio Overview"
                )

        if language:
            select_trigger = self.page.locator("mat-select").first
            if select_trigger.is_visible():
                select_trigger.click()
                self.page.wait_for_selector("mat-option", state="visible")

                option = self.page.locator(
                    f"mat-option:has-text('{language}')")
                if option.is_visible():
                    option.click()
                else:
                    self.page.keyboard.press("Escape")

        if prompt:
            placeholder_snippet = self._get_text("prompt_textarea_placeholder")
            textarea = self.page.locator(
                f"textarea[placeholder*='{placeholder_snippet}']"
            )

            if not textarea.is_visible():
                textarea = self.page.locator(
                    "mat-dialog-container textarea").last

            if textarea.is_visible():
                textarea.fill(prompt)

        generate_btn = self.page.locator(
            f"mat-dialog-actions button:has-text('{self._get_text('generate_button')}')"
        ).last
        if not generate_btn.is_visible():
            generate_btn = self.page.locator("mat-dialog-actions button").last

        generate_btn.click()

        try:
            self.page.wait_for_selector(
                "mat-dialog-container", state="hidden", timeout=5000
            )
        except Exception:
            pass

        time.sleep(2)

        items = self.page.locator(".artifact-library-container")
        count = items.count()

        return str(count)

    def get_status(self, job_id: str) -> Dict[str, str]:
        """Check the status of an audio generation job."""
        try:
            index = int(job_id) - 1
        except ValueError:
            return {"status": "unknown", "error": "Invalid job_id format"}

        parent = self.page.locator("artifact-library")
        children = parent.locator(":scope > *")
        count = children.count()

        if count <= index:
            return {"status": "unknown", "error": "Job ID not found"}

        item = children.nth(index)
        text_content = item.inner_text()

        generating_text = self._get_text("generating_status_text")
        if "sync" in text_content or generating_text in text_content:
            return {"status": "generating"}

        if "play_arrow" in text_content or item.locator(
            "mat-icon:has-text('play_arrow')"
        ).is_visible():
            return {"status": "completed"}

        error_text = self._get_text("error_text")
        if "error" in text_content.lower() or error_text in text_content.lower():
            return {"status": "failed"}

        return {"status": "unknown"}

    def get_download_url(self, job_id: str) -> Optional[str]:
        """Get the direct file URL for generated audio."""
        try:
            index = int(job_id) - 1
        except ValueError:
            logger.error("Invalid job_id format: %s", job_id)
            return None

        parent = self.page.locator("artifact-library")
        items = parent.locator(":scope > *")
        count = items.count()

        if index < 0 or index >= count:
            logger.error("Job ID %s not found (items=%s)", job_id, count)
            return None

        item = items.nth(index)
        try:
            item.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass

        play_btn = item.locator(
            f"button[aria-label='{self._get_text('play_arrow_button')}']"
        ).first

        if not play_btn.is_visible():
            logger.error("Play button not found for job %s", job_id)
            return None

        try:
            play_btn.wait_for(state="visible", timeout=1000)
        except Exception:
            pass

        captured_url: Dict[str, Optional[str]] = {"value": None}

        def route_handler(route, request):
            try:
                if captured_url["value"] is None and request.resource_type == "media":
                    captured_url["value"] = request.url
                    route.abort("blockedbyclient")
                    return
            except Exception:
                pass

            try:
                route.continue_()
            except Exception:
                pass

        pattern = "**/*"

        try:
            self.page.route(pattern, route_handler)

            try:
                play_btn.click()
            except Exception as click_error:
                logger.error(
                    "Failed to click play for job %s: %s", job_id, click_error
                )
                return None

            timeout_seconds = 5
            start_time = time.time()
            while (
                captured_url["value"] is None
                and (time.time() - start_time) < timeout_seconds
            ):
                self.page.wait_for_timeout(100)
        finally:
            try:
                self.page.unroute(pattern, route_handler)
            except Exception:
                pass

        try:
            if captured_url["value"]:
                close_player_button = self.page.locator(
                    f"button[aria-label='{self._get_text('close_audio_player_button')}']"
                )
                if close_player_button.is_visible():
                    close_player_button.first.click()
                return captured_url["value"]

            logger.error("Failed to capture media URL for job %s", job_id)
            return None
        except Exception:
            return None

    def download_file(self, job_id: str) -> Optional[bytes]:
        """Download audio by clicking the Download button in the UI."""
        import os

        try:
            index = int(job_id) - 1
        except ValueError:
            logger.error("Invalid job_id: %s", job_id)
            return None

        download_dir = os.environ.get(
            "DOWNLOAD_DIR", "/home/chromeuser/Downloads")

        # Get list of files BEFORE download (don't delete them!)
        try:
            files_before = set(os.listdir(download_dir))
        except Exception:
            files_before = set()

        try:
            parent = self.page.locator("artifact-library")
            items = parent.locator(":scope > *")
            count = items.count()

            if index < 0 or index >= count:
                logger.error("Job %s not found (count=%d)", job_id, count)
                return None

            item = items.nth(index)
            try:
                item.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass

            more_btn = item.locator(
                f"button[aria-label='{self._get_text('more_button')}']"
            ).first

            if not more_btn.is_visible():
                logger.error("More button not found")
                return None

            more_btn.click()
            self.page.wait_for_timeout(500)

            download_text = self._get_text("download_menu_item")
            download_menu = self.page.get_by_role(
                "menuitem", name=download_text).first

            if not download_menu.is_visible():
                logger.error("Download menu not found")
                self.page.keyboard.press("Escape")
                return None

            logger.info("Clicking Download...")
            download_menu.click()

            # Wait for NEW file to appear
            logger.info("Waiting for new file in %s...", download_dir)
            timeout = 120
            start_time = time.time()
            downloaded_file = None

            while time.time() - start_time < timeout:
                try:
                    files_now = set(os.listdir(download_dir))
                    new_files = files_now - files_before  # Only look at NEW files

                    for f in new_files:
                        if f.endswith(".crdownload") or f.startswith("."):
                            continue
                        filepath = os.path.join(download_dir, f)
                        if os.path.isfile(filepath) and os.path.getsize(filepath) > 0:
                            downloaded_file = filepath
                            logger.info("Found new file: %s", f)
                            break
                except Exception as e:
                    logger.debug("Error listing dir: %s", e)

                if downloaded_file:
                    time.sleep(1)  # Ensure write complete
                    break
                time.sleep(0.5)

            if not downloaded_file:
                logger.error("Download timed out")
                return None

            # Read the file
            with open(downloaded_file, "rb") as f:
                body = f.read()

            logger.info("Downloaded %d bytes from %s",
                        len(body), downloaded_file)

            # Only delete the file we just downloaded (not everything)
            try:
                os.remove(downloaded_file)
            except Exception:
                pass

            return body

        except Exception as e:
            logger.error("Download failed: %s", e)
            import traceback
            traceback.print_exc()
            return None

    def clear_studio(self) -> Dict[str, Any]:
        """Delete all generated audio items."""
        removed = 0
        parent = self.page.locator("artifact-library")
        if parent.count() == 0:
            return {"success": False, "count": 0, "message": "No generated items found"}

        max_attempts = 200
        for _ in range(max_attempts):
            items = parent.locator(":scope > *")
            count = items.count()
            if count == 0:
                break

            item = items.first
            try:
                item.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass

            more_btn = item.locator(
                f"button[aria-label='{self._get_text('more_button')}']"
            ).first

            if more_btn.count() == 0 or not more_btn.is_visible():
                logger.warning(
                    "Could not locate more options for generated item.")
                break

            try:
                more_btn.click()
            except Exception as e:
                logger.error(f"Failed to open menu for generated item: {e}")
                break

            delete_menu = self.page.get_by_role(
                "menuitem", name=self._get_text("delete_menu_item")
            ).first

            if delete_menu.count() == 0 or not delete_menu.is_visible():
                logger.warning(
                    "Delete option not found in generated item menu.")
                break

            delete_menu.click()

            confirm_button = self.page.get_by_role(
                "button", name=self._get_text("confirm_delete_button")
            ).first

            if confirm_button.count() == 0 or not confirm_button.is_visible():
                logger.warning("Delete confirmation button not found.")
                break

            try:
                confirm_button.click()
                item.wait_for(state="detached", timeout=2000)
            except Exception as e:
                logger.warning(f"Generated item did not delete cleanly: {e}")

            removed += 1
            self.page.wait_for_timeout(300)

        return {"success": removed > 0, "count": removed}
